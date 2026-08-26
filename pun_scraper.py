#!/usr/bin/env python3
"""
pun_scraper.py — Scarica periodicamente i punti di ricarica (colonnine) di un
comune dalla Piattaforma Unica Nazionale (PUN) e li accumula in file Parquet.

Contesto tecnico
----------------
Il vecchio pulsante "Esporta dati" + l'endpoint S3 (URL che cambiava di
continuo) sono stati DISABILITATI da GSE a giugno 2026. I dati sono ora
esposti solo tramite l'API REST del portale PUN, autenticata con credenziali
AWS Cognito "guest" (unauthenticated) — nessun login richiesto.

Flusso:
  1. leggi region + IdentityPoolId da /config.json del sito (fallback ai
     valori noti se il formato cambia);
  2. Cognito GetId -> GetCredentialsForIdentity  => credenziali SigV4 (1h);
  3. POST /v1/chargepoints/public/map/search (paginato) => lista evse_id;
  4. POST /v1/chargepoints/group (batch da 100)         => dettagli completi.

Le colonnine dell'area configurata (docs/config.json: un comune, oppure
un'intera regione via CAP — vedi config.py) vengono individuate una volta
(fase "discovery", rieseguita ogni --refresh-discovery ore) e poi solo
quelle vengono ri-interrogate ad ogni ciclo, per non martellare l'API
pubblica.

NB sulla discovery: /v1/chargepoints/public/map/search non espone MAI
location.city/state per i singoli item (solo coordinates/evse_id/status) —
verificato sui dati reali. Il filtro di discovery è quindi sempre e solo
sulla bbox (docs/config.json -> "bbox"), non sul nome comune: il match per
nome comune esiste nel codice solo per il ramo "completo" (quando
map/search non espone nemmeno le coordinate), che con i dati attuali non
scatta mai. Una bbox larga (es. tutta la Sicilia) può quindi raccogliere
qualche colonnina di area limitrofa: è voluto, l'attribuzione precisa
all'area configurata avviene a valle, sui dati salvati, in config.matches_area()
(usato dagli script generate_*.py).

NB sul senso del polling a 5 minuti: il campo `real_time` indica se lo `stato`
della colonnina è aggiornato in tempo reale dal CPO. Per le colonnine con
real_time=True il polling frequente cattura le variazioni di stato
(AVAILABLE/CHARGING/OUTOFORDER...); per le altre lo stato è statico e i cicli
ravvicinati ri-registrano lo stesso valore (il dedup, attivo di default,
evita di riscrivere snapshot identici).

Dipendenze:  pip install boto3 requests pandas pyarrow

Esempi:
  python pun_scraper.py --once                 # un singolo ciclo e termina
  python pun_scraper.py                        # loop ogni 5 min (default)
  python pun_scraper.py --comune Rovereto --provincia TN --interval 600
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import signal
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import boto3
import pandas as pd
import requests
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials

from config import AREA_SLUG, COMUNE, PROVINCIA, BBOX as CONFIG_BBOX

log = logging.getLogger("pun")

# ────────────────────────── COSTANTI / FALLBACK ────────────────────────────

SITE_BASE   = "https://www.piattaformaunicanazionale.it"
CONFIG_URL  = f"{SITE_BASE}/config.json"
API_BASE    = "https://api.pun.piattaformaunicanazionale.it"

# Valori noti (giugno 2026), usati come fallback se /config.json cambia forma.
FALLBACK_REGION  = "eu-south-1"
FALLBACK_POOL_ID = "eu-south-1:e3b2ab05-2046-43dd-8ed0-c0f14c69d507"

MAP_SEARCH_PAGE_SIZE = 1000
GROUP_BATCH_SIZE     = 100
HTTP_TIMEOUT         = 30
USER_AGENT           = "pun-trento-scraper/1.0"

STATUS_MAP = {
    "AVAILABLE": "Attivo", "CHARGING": "Attivo", "RESERVED": "Attivo",
    "PLANNED": "Non Attivo", "OUTOFORDER": "Non Attivo",
    "INOPERATIVE": "Non Attivo", "BLOCKED": "Non Attivo",
    "REMOVED": "Non Attivo", "UNKNOWN": "Non Attivo",
}
DC_STANDARDS = {"CHADEMO", "IEC_62196_T2_COMBO", "TESLA_R", "TESLA_S",
                "IEC_62196_T1_COMBO", "NACS"}

# ────────────────────────── UTILITY ────────────────────────────────────────

def normalize(s: str) -> str:
    if not s:
        return ""
    s = s.strip().lower().replace("\u2019", "'").replace("`", "'")
    s = "".join(c for c in unicodedata.normalize("NFD", s)
                if unicodedata.category(c) != "Mn")
    s = re.sub(r"[.'\-/]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _clean(v):
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def in_bbox(lat, lon, bbox) -> bool:
    la0, la1, lo0, lo1 = bbox
    return la0 <= lat <= la1 and lo0 <= lon <= lo1


# ────────────────────────── AUTH (Cognito guest) ───────────────────────────

class PunSession:
    """Sessione autenticata verso l'API PUN. Gestisce l'ottenimento e il
    rinnovo automatico delle credenziali Cognito guest e firma SigV4."""

    def __init__(self, region: str, pool_id: str):
        self.region = region
        self.pool_id = pool_id
        self._cognito = boto3.client(
            "cognito-identity", region_name=region,
            aws_access_key_id="", aws_secret_access_key="",  # endpoint pubblico
        )
        self._creds: Credentials | None = None
        self._exp: float = 0.0
        self._http = requests.Session()
        self._http.headers["User-Agent"] = USER_AGENT

    def _ensure_creds(self):
        if self._creds and time.time() < self._exp - 120:
            return
        iid = self._cognito.get_id(IdentityPoolId=self.pool_id)["IdentityId"]
        c = self._cognito.get_credentials_for_identity(IdentityId=iid)["Credentials"]
        self._creds = Credentials(c["AccessKeyId"], c["SecretKey"], c["SessionToken"])
        # boto3 restituisce datetime tz-aware
        self._exp = c["Expiration"].timestamp()
        log.info("credenziali Cognito ottenute (scadenza %s)",
                 c["Expiration"].isoformat())

    def post(self, path: str, payload) -> requests.Response:
        self._ensure_creds()
        url = f"{API_BASE}{path}"
        body = json.dumps(payload)
        req = AWSRequest(method="POST", url=url, data=body,
                         headers={"Content-Type": "application/json"})
        SigV4Auth(self._creds, "execute-api", self.region).add_auth(req)
        return self._http.send(
            requests.Request(method="POST", url=url, data=body,
                             headers=dict(req.headers)).prepare(),
            timeout=HTTP_TIMEOUT,
        )


def load_config() -> tuple[str, str]:
    """Legge region + IdentityPoolId da /config.json; fallback ai valori noti."""
    try:
        r = requests.get(CONFIG_URL, headers={"User-Agent": USER_AGENT}, timeout=15)
        r.raise_for_status()
        cfg = r.json()
        blob = json.dumps(cfg)
        pool = re.search(r"([a-z]{2}-[a-z]+-\d:[0-9a-f-]{36})", blob)
        region_m = re.search(r'"(?:region|awsRegion|aws_region)"\s*:\s*"([a-z0-9-]+)"', blob)
        pool_id = pool.group(1) if pool else FALLBACK_POOL_ID
        region = region_m.group(1) if region_m else pool_id.split(":")[0]
        log.info("config.json: region=%s pool=%s", region, pool_id)
        return region, pool_id
    except Exception as e:  # noqa: BLE001
        log.warning("config.json non leggibile (%s) — uso i valori di fallback", e)
        return FALLBACK_REGION, FALLBACK_POOL_ID


# ────────────────────────── FETCH ──────────────────────────────────────────

def fetch_map_search(sess: PunSession) -> list[dict]:
    """Scarica tutte le voci della mappa (paginato). Ritorna i raw item."""
    out, page = [], 0
    while True:
        r = sess.post("/v1/chargepoints/public/map/search",
                      {"page": page, "size": MAP_SEARCH_PAGE_SIZE})
        r.raise_for_status()
        d = r.json()
        content = d.get("content", [])
        out.extend(content)
        if page == 0:
            log.info("map/search: %s elementi totali, %s pagine",
                     d.get("totalElements", "?"), d.get("totalPages", "?"))
        if d.get("last", True) or not content:
            break
        page += 1
    log.info("map/search: raccolti %s item", len(out))
    return out


def fetch_group(sess: PunSession, evse_ids: list[str]) -> list[dict]:
    """Dettagli completi per una lista di evse_id (batch da 100)."""
    records = []
    for i in range(0, len(evse_ids), GROUP_BATCH_SIZE):
        batch = evse_ids[i:i + GROUP_BATCH_SIZE]
        r = sess.post("/v1/chargepoints/group", batch)
        if r.status_code == 401:            # creds scadute: rinnova e riprova
            sess._creds = None
            r = sess.post("/v1/chargepoints/group", batch)
        r.raise_for_status()
        records.extend(r.json())
        time.sleep(0.05)
    return records


# ────────────────────────── PARSING ────────────────────────────────────────

def record_comune(rec: dict) -> tuple[str, str, float | None, float | None]:
    loc = rec.get("location", {}) or {}
    coords = rec.get("coordinates", {}) or {}
    try:
        lat = float(coords.get("latitude"))
        lon = float(coords.get("longitude"))
    except (TypeError, ValueError):
        lat = lon = None
    return (normalize(loc.get("city", "")), normalize(loc.get("state", "")), lat, lon)


def matches_comune(rec: dict, comune_n: str, prov_n: str, bbox) -> bool:
    """comune_n vuoto (modalità regione, COMUNE=None in config) => il primo
    ramo (match per nome comune) non scatta mai e si passa dritti al bbox,
    che nella pratica (vedi NB in cima al file) è comunque l'unico ramo
    usato davvero, anche in modalità comune."""
    city, state, lat, lon = record_comune(rec)
    if comune_n and city and city == comune_n:
        # conferma provincia se disponibile, altrimenti accetta sul nome città
        return (not prov_n) or (not state) or prov_n in state or state == comune_n
    if not city and lat is not None and in_bbox(lat, lon, bbox):
        return True
    return False


def parse_record(rec: dict, ts: str) -> dict | None:
    loc = rec.get("location", {}) or {}
    coords = rec.get("coordinates", {}) or {}
    try:
        lat = round(float(coords.get("latitude")), 6)
        lon = round(float(coords.get("longitude")), 6)
    except (TypeError, ValueError):
        return None

    conns = rec.get("connectors", []) or []
    main = max(conns, key=lambda c: c.get("max_electric_power", 0), default={})
    standard = _clean(main.get("standard"))
    power_w = main.get("max_electric_power")
    corrente = "DC" if standard in DC_STANDARDS else ("AC" if standard else None)
    status_raw = _clean(rec.get("status"))
    opening = loc.get("opening_times", {}) or {}

    return {
        "ts": ts,
        "id_evse": _clean(rec.get("evse_id")),
        "stato": STATUS_MAP.get(status_raw, "Non Attivo"),
        "stato_raw": status_raw,
        "real_time": bool(rec.get("realTime")),
        "cpo": _clean(rec.get("businessName")),
        "indirizzo": _clean(loc.get("address")),
        "citta": _clean(loc.get("city")),
        "cap": _clean(loc.get("postal_code")),
        "lat": lat, "lon": lon,
        "potenza_w": int(power_w) if power_w else None,
        "corrente": corrente,
        "standard_connettore": standard,
        "n_connettori": len(conns),
        "open_24h7": bool(opening.get("twentyfourseven", False)),
        "party_id": _clean(loc.get("party_id")),
        "capabilities": "|".join(rec.get("capabilities", []) or []) or None,
        "publication_status": _clean(rec.get("publicationStatus")),
    }


# ────────────────────────── DISCOVERY ──────────────────────────────────────

def discover_ids(sess, comune, provincia, bbox, cache: Path, max_age_h: float,
                 force=False) -> list[str]:
    """Ritorna gli evse_id del comune, usando la cache se ancora valida."""
    if not force and cache.exists():
        age_h = (time.time() - cache.stat().st_mtime) / 3600
        if age_h < max_age_h:
            ids = json.loads(cache.read_text())["evse_ids"]
            log.info("discovery da cache (%.1fh, %s colonnine)", age_h, len(ids))
            return ids

    comune_n, prov_n = normalize(comune), normalize(provincia)
    items = fetch_map_search(sess)

    # Percorso economico: se map/search già espone city/coordinate, filtra qui.
    if items and (items[0].get("location") or items[0].get("coordinates")):
        matched = [it["evse_id"] for it in items
                   if it.get("evse_id") and matches_comune(it, comune_n, prov_n, bbox)]
        log.info("discovery (via map/search) — %s colonnine in %s", len(matched), comune)
    else:
        # Percorso completo: servono i dettagli per conoscere il comune.
        log.info("map/search non espone il comune: scarico i dettagli (può "
                 "richiedere qualche minuto, una volta al giorno)...")
        ids = [it["evse_id"] for it in items if it.get("evse_id")]
        recs = fetch_group(sess, ids)
        matched = [r["evse_id"] for r in recs
                   if matches_comune(r, comune_n, prov_n, bbox)]
        log.info("discovery (via group) — %s colonnine in %s", len(matched), comune)

    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(
        {"comune": comune, "provincia": provincia,
         "updated": datetime.now(timezone.utc).isoformat(),
         "evse_ids": matched}, ensure_ascii=False, indent=2))
    return matched


# ────────────────────────── SCRITTURA PARQUET ──────────────────────────────

def snapshot_hash(rows: list[dict]) -> str:
    """Hash dei campi 'di stato' (esclude ts) per il dedup fra cicli."""
    keys = ("id_evse", "stato_raw", "potenza_w", "standard_connettore",
            "n_connettori", "publication_status")
    payload = sorted(tuple(r.get(k) for k in keys) for r in rows)
    return hashlib.md5(json.dumps(payload, default=str).encode()).hexdigest()


def _ts_compact(ts: str) -> str:
    """'2026-08-04T10:05:00+00:00' -> '20260804T100500Z'."""
    return ts[:19].replace("-", "").replace(":", "") + "Z"


def write_snapshot(rows, outdir: Path, statedir: Path, dedup: bool,
                   layout: str = "partitioned") -> bool:
    """Scrive lo snapshot. Ritorna True se ha scritto, False se saltato (dedup).

    layout='partitioned' (default): un file write-once per snapshot in
        data/date=YYYY-MM-DD/<ts>.parquet — non riscrive mai nulla, ideale per
        il commit su git (ogni blob salvato una volta sola).
    layout='daily': un unico parquet giornaliero riscritto ad ogni ciclo
        (data/<outdir>_YYYY-MM-DD.parquet).
    """
    if not rows:
        log.warning("nessuna riga da scrivere")
        return False

    ts = rows[0]["ts"]
    day = ts[:10]
    outdir.mkdir(parents=True, exist_ok=True)
    statedir.mkdir(parents=True, exist_ok=True)

    h = snapshot_hash(rows)
    hash_file = statedir / ("last.hash" if layout == "partitioned"
                            else f"{day}.lasthash")
    if dedup and hash_file.exists() and hash_file.read_text().strip() == h:
        log.info("snapshot identico al precedente — salto (dedup)")
        return False

    new = pd.DataFrame(rows)

    if layout == "partitioned":
        part = outdir / f"date={day}"
        part.mkdir(parents=True, exist_ok=True)
        target = part / f"{_ts_compact(ts)}.parquet"
        new.to_parquet(target, index=False, compression="zstd")  # write-once
        hash_file.write_text(h)
        log.info("scritte %s righe -> %s", len(new), target.relative_to(outdir.parent))
        return True

    # layout == "daily"
    target = outdir / f"{outdir.name}_{day}.parquet"
    if target.exists():
        df = pd.concat([pd.read_parquet(target), new], ignore_index=True)
    else:
        df = new
    tmp = target.with_suffix(".parquet.tmp")
    df.to_parquet(tmp, index=False, compression="zstd")
    tmp.replace(target)
    hash_file.write_text(h)
    log.info("scritte %s righe -> %s (totale giornata: %s)",
             len(new), target.name, len(df))
    return True


# ────────────────────────── CICLO ──────────────────────────────────────────

def run_cycle(sess, args, bbox) -> None:
    statedir = Path(args.statedir)
    # args.comune (default: config.COMUNE, o sovrascritto da CLI) guida il
    # nome cache in modalità comune; in modalità regione args.comune è None
    # (config.COMUNE assente) e si usa lo slug dell'area (es. "sicilia").
    area_slug = normalize(args.comune).replace(' ', '_') if args.comune else (AREA_SLUG or 'area')
    cache = statedir / f"discovery_{area_slug}.json"
    ids = discover_ids(sess, args.comune, args.provincia, bbox, cache,
                       args.refresh_discovery)
    if not ids:
        log.error("nessuna colonnina trovata per %s (%s)", args.comune, args.provincia)
        return
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    recs = fetch_group(sess, ids)
    rows = [p for p in (parse_record(r, ts) for r in recs) if p]
    attivi = sum(1 for r in rows if r["stato"] == "Attivo")
    log.info("ciclo %s: %s colonnine (%s attive)", ts, len(rows), attivi)
    write_snapshot(rows, Path(args.outdir), statedir,
                   dedup=not args.no_dedup, layout=args.layout)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--comune", default=COMUNE)
    ap.add_argument("--provincia", default=PROVINCIA)
    ap.add_argument("--outdir", default="./data",
                    help="cartella dei parquet di output (default: ./data)")
    ap.add_argument("--statedir", default="./state",
                    help="cartella per cache discovery + lasthash (default: ./state)")
    ap.add_argument("--interval", type=int, default=300,
                    help="secondi fra un ciclo e l'altro (default: 300 = 5 min)")
    ap.add_argument("--once", action="store_true", help="esegui un solo ciclo")
    ap.add_argument("--refresh-discovery", type=float, default=24.0,
                    help="ore fra due discovery complete (default: 24)")
    ap.add_argument("--layout", choices=["partitioned", "daily"],
                    default="partitioned",
                    help="partitioned: un file write-once per snapshot in "
                         "date=YYYY-MM-DD/ (default, minimo impatto su git); "
                         "daily: unico parquet giornaliero riscritto ogni ciclo")
    ap.add_argument("--no-dedup", action="store_true",
                    help="scrivi ogni ciclo anche se identico al precedente")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")

    # bbox da docs/config.json (vedi NB in cima al file: è il filtro di
    # discovery vero e proprio, non solo un fallback). Se assente in config
    # e si sta passando un comune diverso da quello di default via CLI,
    # niente bbox: si confida solo sul match per nome comune (ramo che con
    # i dati attuali di map/search però non scatta mai — vedi NB).
    bbox = CONFIG_BBOX if CONFIG_BBOX else (0, 0, 0, 0)

    region, pool_id = load_config()
    sess = PunSession(region, pool_id)

    stop = {"flag": False}
    signal.signal(signal.SIGINT, lambda *_: stop.__setitem__("flag", True))
    signal.signal(signal.SIGTERM, lambda *_: stop.__setitem__("flag", True))

    while True:
        t0 = time.time()
        try:
            run_cycle(sess, args, bbox)
        except Exception as e:  # noqa: BLE001
            log.exception("errore nel ciclo: %s", e)
        if args.once or stop["flag"]:
            break
        sleep = max(1, args.interval - (time.time() - t0))
        log.info("attendo %.0fs...", sleep)
        for _ in range(int(sleep)):
            if stop["flag"]:
                break
            time.sleep(1)
        if stop["flag"]:
            break

    log.info("terminato.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
