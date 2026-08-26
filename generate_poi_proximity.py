"""
generate_poi_proximity.py — Per ogni categoria di punto di interesse
(musei, supermercati, banche, ospedali, ambulatori) calcola quante colonnine
cittadine sono entro SOGLIA_METRI dal più vicino, sull'ultimo snapshot.

Sorgente dei POI: poi_<area>.json (config.POI_FILE), generato una tantum da fetch_poi.py
(OpenStreetMap via Overpass, licenza ODbL — vedi quel file per i dettagli
e il perché non si usa dati.trentino.it). Questo script NON interroga
Overpass: legge solo il file statico già scaricato.

Le colonnine A22 sono escluse (stesso motivo di generate_trends.py: pubblico
di transito, non urbano — la prossimità a un museo cittadino non è una
statistica sensata per un'area di servizio autostradale).

Va eseguito una volta al giorno, dopo generate_stats.py.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd
import pyarrow.dataset as ds

from config import POI_FILE, matches_area

ROOT = Path(__file__).resolve().parent
DATASET = ROOT / 'data'
OUT = ROOT / 'docs' / 'stats' / 'data' / 'poi_proximity.json'

SOGLIA_METRI = 300

CATEGORY_LABELS = {
    'musei': 'Musei',
    'supermercati': 'Supermercati',
    'banche': 'Banche',
    'ospedali': 'Ospedali',
    'ambulatori': 'Ambulatori',
    'svincoli_autostradali': 'Svincoli autostradali',
    'incroci_primarie': 'Incroci di strade primarie',
}


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def load_latest_city() -> pd.DataFrame:
    table = ds.dataset(str(DATASET), format='parquet', partitioning='hive').to_table().to_pandas()
    table['ts'] = pd.to_datetime(table['ts'], utc=True)
    latest = table.sort_values('ts').drop_duplicates(subset=['id_evse'], keep='last').copy()
    # Solo l'area configurata (non le zone limitrofe, non l'A22).
    is_comune = matches_area(latest['citta'], latest['cap'])
    return latest[is_comune]


def nearest(lat: float, lon: float, pois: list[dict]) -> tuple[dict, float] | None:
    best, best_d = None, None
    for poi in pois:
        d = haversine_m(lat, lon, poi['lat'], poi['lon'])
        if best_d is None or d < best_d:
            best, best_d = poi, d
    return (best, best_d) if best is not None else None


def analizza_categoria(colonnine: pd.DataFrame, pois: list[dict]) -> dict | None:
    if not pois:
        return None
    entro_soglia = 0
    esempio = None
    for _, row in colonnine.iterrows():
        result = nearest(row['lat'], row['lon'], pois)
        if result is None:
            continue
        poi, dist = result
        if dist <= SOGLIA_METRI:
            entro_soglia += 1
            if esempio is None or dist < esempio['distanza_m']:
                esempio = {
                    'colonnina_indirizzo': row['indirizzo'] or 'indirizzo sconosciuto',
                    'poi_nome': poi['name'],
                    'distanza_m': round(dist),
                }
    totale = len(colonnine)
    return {
        'count_entro_soglia': entro_soglia,
        'share': round(entro_soglia / totale * 100, 1) if totale else 0,
        'esempio': esempio,
    }


def main() -> None:
    if not POI_FILE.exists():
        print(f'{POI_FILE} non trovato: esegui prima fetch_poi.py. poi_proximity.json non generato')
        return

    poi_data = json.loads(POI_FILE.read_text(encoding='utf-8'))
    colonnine = load_latest_city()
    totale = len(colonnine)

    categorie = {}
    for cat_key, label in CATEGORY_LABELS.items():
        pois = poi_data.get('categories', {}).get(cat_key, [])
        risultato = analizza_categoria(colonnine, pois)
        if risultato is None:
            continue
        categorie[cat_key] = {'label': label, 'n_poi': len(pois), **risultato}

    payload = {
        'generated_at': pd.Timestamp.now('UTC').isoformat(),
        'fonte_poi': poi_data.get('source', 'OpenStreetMap'),
        'poi_generated_at': poi_data.get('generated_at'),
        'soglia_metri': SOGLIA_METRI,
        'totale_colonnine_citta': totale,
        'categorie': categorie,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print('generato', OUT)
    for cat_key, v in categorie.items():
        print(f"  {v['label']}: {v['count_entro_soglia']}/{totale} ({v['share']}%)")


if __name__ == '__main__':
    main()
