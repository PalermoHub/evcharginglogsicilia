"""
generate_poi_usage.py — Per ogni singolo punto di interesse (non per
categoria aggregata, a differenza di generate_poi_proximity.py) conta
quante colonnine monitorabili sono entro SOGLIA_METRI e, fra quelle, quante
sono state effettivamente USATE (almeno una sessione di ricarica osservata
nello storico raccolto finora) — con breakdown per fascia di potenza, per
il filtro lato frontend della pagina Statistiche.

Sorgenti: poi_<area>.json (config.POI_FILE, elenco POI — vedi generate_poi_proximity.py per
la provenienza OSM/ODbL), l'ultimo snapshot del dataset parquet (posizione e
potenza delle colonnine) e stations_usage.json già generato da
generate_station_usage.py (n_sessioni per colonnina) — va quindi eseguito
DOPO generate_station_usage.py.

Solo colonnine cittadine usage_observable: senza un operatore che distingua
occupata da libera "usata" non è calcolabile (stesso criterio di
generate_station_usage.py, vedi usage_semantics.py).
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd
import pyarrow.dataset as ds

from config import POI_FILE, matches_area
from usage_semantics import cpos_with_charging, usage_observable

ROOT = Path(__file__).resolve().parent
DATASET = ROOT / 'data'
USAGE_FILE = ROOT / 'docs' / 'stations_usage.json'
OUT = ROOT / 'docs' / 'stats' / 'data' / 'poi_usage.json'

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

POWER_TIERS = ('lenta', 'rapida', 'ultra')


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


def load_monitorabili_city() -> list[dict]:
    table = ds.dataset(str(DATASET), format='parquet', partitioning='hive').to_table().to_pandas()
    table['ts'] = pd.to_datetime(table['ts'], utc=True)
    charging_cpos = cpos_with_charging(table)
    table['usage_observable'] = usage_observable(table, charging_cpos)
    is_comune = matches_area(table['citta'], table['cap'])
    latest = table[is_comune & table['usage_observable']].sort_values('ts').drop_duplicates(
        subset=['id_evse'], keep='last'
    )
    usage = {}
    if USAGE_FILE.exists():
        usage = json.loads(USAGE_FILE.read_text(encoding='utf-8')).get('stazioni', {})

    stazioni = []
    for _, row in latest.iterrows():
        rec_usage = usage.get(row['id_evse'], {})
        stazioni.append({
            'id_evse': row['id_evse'],
            'indirizzo': row['indirizzo'] or 'indirizzo sconosciuto',
            'lat': float(row['lat']),
            'lon': float(row['lon']),
            'fascia_potenza': power_tier(row['potenza_w']),
            'n_sessioni': rec_usage.get('n_sessioni', 0),
        })
    return stazioni


def main() -> None:
    if not POI_FILE.exists():
        print(f'{POI_FILE} non trovato: esegui prima fetch_poi.py. poi_usage.json non generato')
        return

    poi_data = json.loads(POI_FILE.read_text(encoding='utf-8'))
    stazioni = load_monitorabili_city()
    if not stazioni:
        print('nessuna colonnina monitorabile in città: poi_usage.json non generato')
        return

    pois_out = []
    for cat_key, label in CATEGORY_LABELS.items():
        for poi in poi_data.get('categories', {}).get(cat_key, []):
            entro_soglia = []
            for s in stazioni:
                d = haversine_m(poi['lat'], poi['lon'], s['lat'], s['lon'])
                if d <= SOGLIA_METRI:
                    entro_soglia.append((s, round(d)))
            usate = [(s, d) for s, d in entro_soglia if s['n_sessioni'] > 0]
            by_power = {
                tier: sum(1 for s, _ in usate if s['fascia_potenza'] == tier)
                for tier in POWER_TIERS
            }
            esempio = None
            if usate:
                s, d = min(usate, key=lambda item: item[1])
                esempio = {'colonnina_indirizzo': s['indirizzo'], 'distanza_m': d}

            pois_out.append({
                'name': poi['name'],
                'categoria': cat_key,
                'categoria_label': label,
                'lat': poi['lat'],
                'lon': poi['lon'],
                'n_colonnine_entro_soglia': len(entro_soglia),
                'n_colonnine_usate': len(usate),
                'n_usate_by_power': by_power,
                'esempio': esempio,
            })

    payload = {
        'generated_at': pd.Timestamp.now('UTC').isoformat(),
        'fonte_poi': poi_data.get('source', 'OpenStreetMap'),
        'soglia_metri': SOGLIA_METRI,
        'pois': pois_out,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    con_uso = sum(1 for p in pois_out if p['n_colonnine_usate'] > 0)
    print(f'generato {OUT} ({len(pois_out)} POI, {con_uso} con almeno una colonnina usata nelle vicinanze)')


if __name__ == '__main__':
    main()
