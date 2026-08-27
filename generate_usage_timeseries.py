"""
generate_usage_timeseries.py — Una riga per (colonnina monitorabile × giorno)
con tutte le dimensioni di filtro (fascia di potenza, operatore, categorie
POI vicine) e le metriche d'uso di quel giorno (sessioni, energia stimata,
durata, intensità oraria). Pensato per essere aggregato lato client con
qualunque combinazione di filtro/granularità (ora/giorno/settimana/mese)
sulla pagina Statistiche, senza dover precalcolare ogni combinazione qui.

Stessa logica di rilevazione sessioni di generate_station_usage.py
(duplicata qui invece di importata: stesso stile del resto del repo, dove
ogni script di generazione resta eseguibile da solo — vedi es. le costanti
colore duplicate in docs/app.js e docs/stats/app.js).

Solo colonnine cittadine usage_observable (le altre non hanno una
"sessione" da rilevare, vedi generate_station_usage.py e
usage_semantics.py) e non le autostrade (stesso motivo di generate_trends.py:
pubblico di transito, non urbano).

Va eseguito dopo generate_station_usage.py e generate_poi_proximity.py
(quest'ultimo scarica/legge poi_trento.json, qui si riusa solo la sorgente
POI, non il suo output aggregato per categoria).
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd
import pyarrow.dataset as ds

from config import AREA_NOME, POI_FILE, matches_area
from usage_semantics import cpos_with_charging, usage_observable

ROOT = Path(__file__).resolve().parent
DATASET = ROOT / 'data'
OUT = ROOT / 'docs' / 'stats' / 'data' / 'usage_timeseries.json'

SOGLIA_METRI_POI = 300
GAP_MASSIMO_MINUTI = 20  # stessa soglia di generate_station_usage.py


def power_tier(potenza_w) -> str | None:
    if pd.isna(potenza_w):
        return None
    w = float(potenza_w)
    if w <= 22000:
        return 'lenta'
    if w <= 50000:
        return 'rapida'
    return 'ultra'


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def load_usage_observable_city() -> pd.DataFrame:
    table = ds.dataset(str(DATASET), format='parquet', partitioning='hive').to_table().to_pandas()
    table['ts'] = pd.to_datetime(table['ts'], utc=True)
    charging_cpos = cpos_with_charging(table)
    table['usage_observable'] = usage_observable(table, charging_cpos)
    is_comune = matches_area(table['citta'], table['cap'])
    table = table[table['usage_observable'] & is_comune].copy()
    table['is_charging'] = table['stato_raw'].fillna('').str.upper().eq('CHARGING')
    return table


def detect_sessions(seq: list[tuple[pd.Timestamp, bool]]) -> list[dict]:
    """Stessa logica di generate_station_usage.py::detect_sessions, ma
    ritorna solo le sessioni chiuse (quella in corso all'ultima rilevazione
    non ha una data di fine certa: non entra in questa serie storica)."""
    sessions = []
    current = None
    max_gap = pd.Timedelta(GAP_MASSIMO_MINUTI, unit='m')
    for ts, charging in seq:
        if charging:
            if current is None:
                current = {'inizio': ts, 'fine': ts}
            elif ts - current['fine'] > max_gap:
                sessions.append(current)
                current = {'inizio': ts, 'fine': ts}
            else:
                current['fine'] = ts
        else:
            if current is not None:
                sessions.append(current)
                current = None
    return sessions


def durata_minuti(sess: dict) -> float:
    return (sess['fine'] - sess['inizio']).total_seconds() / 60.0


def poi_categorie_vicine(lat: float, lon: float, poi_data: dict) -> list[str]:
    categorie = []
    for cat_key, pois in poi_data.get('categories', {}).items():
        best = None
        for poi in pois:
            d = haversine_m(lat, lon, poi['lat'], poi['lon'])
            if best is None or d < best:
                best = d
        if best is not None and best <= SOGLIA_METRI_POI:
            categorie.append(cat_key)
    return categorie


def main() -> None:
    table = load_usage_observable_city()
    if table.empty:
        print(f'nessuna colonnina con occupazione osservabile a {AREA_NOME} nel dataset: usage_timeseries.json non generato')
        return

    poi_data = json.loads(POI_FILE.read_text(encoding='utf-8')) if POI_FILE.exists() else {'categories': {}}

    rows = []
    for id_evse, g in table.sort_values('ts').groupby('id_evse'):
        g = g.sort_values('ts')
        cpo = g['cpo'].iloc[-1] or 'operatore sconosciuto'
        potenza_nota = g['potenza_w'].dropna()
        potenza_w = float(potenza_nota.iloc[-1]) if not potenza_nota.empty else None
        fascia = power_tier(potenza_w)
        lat, lon = float(g['lat'].iloc[-1]), float(g['lon'].iloc[-1])
        categorie = poi_categorie_vicine(lat, lon, poi_data)

        # Sessioni chiuse, con la data attribuita al giorno di inizio (stesso
        # criterio di giorno_record in generate_station_usage.py).
        sessions = detect_sessions(list(zip(g['ts'], g['is_charging'])))
        per_data: dict[str, dict] = {}
        for s in sessions:
            data = s['inizio'].strftime('%Y-%m-%d')
            slot = per_data.setdefault(data, {'n_sessioni': 0, 'durata_totale_minuti': 0.0, 'ore': [0] * 24})
            slot['n_sessioni'] += 1
            slot['durata_totale_minuti'] += durata_minuti(s)
            slot['ore'][s['inizio'].hour] = 1

        # Intensità oraria: per ogni giorno con almeno una rilevazione
        # charging, quali ore del giorno hanno visto la colonnina in carica
        # (indipendentemente dal fatto che la sessione sia stata chiusa o
        # meno) — copre anche il caso di una sessione ancora in corso.
        charging_obs = g[g['is_charging']]
        for (data, ora), _ in charging_obs.groupby([charging_obs['date'], charging_obs['ts'].dt.hour]):
            slot = per_data.setdefault(str(data), {'n_sessioni': 0, 'durata_totale_minuti': 0.0, 'ore': [0] * 24})
            slot['ore'][ora] = 1

        for data, slot in per_data.items():
            durata = round(slot['durata_totale_minuti'], 1)
            rows.append({
                'date': data,
                'id_evse': id_evse,
                'cpo': cpo,
                'fascia_potenza': fascia,
                'poi_categorie': categorie,
                'n_sessioni': slot['n_sessioni'],
                'kwh_stimato': round(durata / 60.0 * potenza_w / 1000.0, 2) if potenza_w else None,
                'durata_totale_minuti': durata,
                'ore_charging': slot['ore'],
            })

    payload = {
        'generated_at': pd.Timestamp.now('UTC').isoformat(),
        'soglia_metri_poi': SOGLIA_METRI_POI,
        'nota': (
            'Una riga per colonnina monitorabile e giorno. energia/durata coprono solo le sessioni '
            'chiuse quel giorno (stessa stima per difetto di stations_usage.json); ore_charging segna '
            "invece qualunque ora con almeno una rilevazione in carica, inclusa un'eventuale sessione "
            'ancora in corso.'
        ),
        'rows': rows,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'generato {OUT} ({len(rows)} righe)')


if __name__ == '__main__':
    main()
