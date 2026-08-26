"""Configurazione condivisa: area geografica monitorata (comune o regione).

Unica fonte di verità in docs/config.json, letta sia dagli script Python
(qui) sia dal sito statico (docs/shared-config.js, via fetch a runtime).

Due modalità, scelte dalle chiavi presenti in docs/config.json:
  - comune (default storico):  {"comune": "Trento", "provincia": "TN", "bbox": [...]}
  - regione (CAP-based):       {"area_nome": "Sicilia", "cap_min": "90000",
                                 "cap_max": "98168", "bbox": [...]}
In modalità regione il filtro sulle righe è sul CAP (vedi matches_area),
molto più robusto su un'area con centinaia di comuni che un confronto per
nome comune. La bbox resta il filtro usato in fase di *discovery* da
pun_trento.py in entrambe le modalità (vedi commenti lì: l'API PUN non
espone il comune nella scansione economica, solo le coordinate).

Il confronto con un'autostrada/rete specifica (es. A22 per Trento) è
opzionale e vive anch'esso qui, sotto "confronto_autostrada" — assente per
un'area dove non ha senso o non è riconoscibile nei dati. Il segnale nei
dati varia da area ad area (per Trento è il CPO/prefisso ID, perché l'A22
gestisce colonnine proprie; altrove può essere solo il testo
dell'indirizzo, se il gestore è uno dei CPO "normali" e la sola cosa che
tradisce l'area di servizio è l'indirizzo) — "confronto_autostrada" accetta
perciò id_prefix/cpo_match/indirizzo_pattern, tutti opzionali, in OR fra
loro: si popolano solo quelli per cui c'è un segnale verificato nei dati
reali, mai per supposizione (rischio di falsi positivi/negativi silenziosi
altrimenti — vedi is_autostrada sotto).
"""
from __future__ import annotations

import json
import unicodedata
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
_CONFIG_PATH = ROOT / 'docs' / 'config.json'
_config = json.loads(_CONFIG_PATH.read_text(encoding='utf-8'))

# Modalità comune (default storico). None in modalità regione.
COMUNE = _config.get('comune')
PROVINCIA = _config.get('provincia')
COMUNE_NORM = COMUNE.strip().lower() if COMUNE else None

# Modalità regione (CAP-based). None/assenti in modalità comune.
CAP_MIN = _config.get('cap_min')
CAP_MAX = _config.get('cap_max')

# Nome mostrato in UI e nei testi generati; in modalità comune coincide col
# nome del comune se non specificato esplicitamente.
AREA_NOME = _config.get('area_nome') or COMUNE

# bbox comune a entrambe le modalità: (lat_min, lat_max, lon_min, lon_max).
BBOX = tuple(_config['bbox']) if 'bbox' in _config else None

# {"id_prefix": ..., "cpo_match": ..., "indirizzo_pattern": ..., "label": ...}
# o None se non applicabile all'area (vedi is_autostrada sotto).
AUTOSTRADA = _config.get('confronto_autostrada')

# Sigla mostrata in badge/testi (es. "A22", "A19"): letta da AUTOSTRADA così
# non resta hardcoded nel frontend/nei testi generati per una singola area.
AUTOSTRADA_LABEL = AUTOSTRADA.get('label') if AUTOSTRADA else None


def _slug(name: str) -> str:
    s = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode('ascii')
    return ''.join(c if c.isalnum() else '_' for c in s.strip().lower()).strip('_')


# Slug ascii dell'area (es. "sicilia", "trento"): usato per nominare file
# derivati dall'area configurata (POI_FILE sotto, cache di discovery in
# pun_scraper.py) senza duplicare la logica di slug in più punti.
AREA_SLUG = _slug(AREA_NOME) if AREA_NOME else None

# File dei punti di interesse (musei, supermercati...) per quest'area,
# generato una tantum da fetch_poi.py e letto da generate_poi_proximity.py/
# generate_poi_usage.py. Un solo punto di verità sul nome, per evitare che
# scraper e script di aggregazione divergano su quale file leggere.
POI_FILE = ROOT / f'poi_{AREA_SLUG}.json' if AREA_SLUG else None


def matches_area(citta, cap):
    """Serie booleana pandas: True per le righe che appartengono all'area
    configurata. Prende in input le colonne citta/cap di un DataFrame.

    Modalità regione (CAP_MIN/CAP_MAX in config): confronto numerico sul
    CAP, zero-paddato a 5 cifre.
    Modalità comune (default storico): uguaglianza sul nome comune
    (comportamento identico a prima del supporto multi-comune).
    """
    if CAP_MIN and CAP_MAX:
        cap_norm = cap.fillna('').astype(str).str.strip().str.zfill(5)
        return (cap_norm >= CAP_MIN.zfill(5)) & (cap_norm <= CAP_MAX.zfill(5))
    return citta.fillna('').str.strip().str.lower() == COMUNE_NORM


def is_autostrada(id_evse, cpo, indirizzo=None):
    """Serie booleana pandas: True per le righe della rete autostradale
    configurata (es. A22 per Trento, A19 per la Sicilia) — riconoscibile
    solo per i segnali effettivamente presenti in AUTOSTRADA
    (id_prefix/cpo_match/indirizzo_pattern, in OR fra loro, tutti
    opzionali), mai un rilevamento generico "colonnina autostradale" (vedi
    commenti in generate_curiosities.py). Tutta False se l'area configurata
    non ha un confronto di questo tipo (AUTOSTRADA assente)."""
    if not AUTOSTRADA:
        return pd.Series(False, index=id_evse.index)
    match = pd.Series(False, index=id_evse.index)
    if AUTOSTRADA.get('id_prefix'):
        match |= id_evse.fillna('').str.upper().str.startswith(AUTOSTRADA['id_prefix'].upper())
    if AUTOSTRADA.get('cpo_match'):
        match |= cpo.fillna('').str.contains(AUTOSTRADA['cpo_match'], case=False, na=False)
    if AUTOSTRADA.get('indirizzo_pattern') and indirizzo is not None:
        match |= indirizzo.fillna('').str.contains(AUTOSTRADA['indirizzo_pattern'], case=False, na=False, regex=True)
    return match
