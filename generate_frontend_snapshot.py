from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pyarrow.dataset as ds

from config import is_autostrada, matches_area
from usage_semantics import cpos_with_charging, usage_observable

ROOT = Path(__file__).resolve().parent
DATASET = ROOT / 'data'
OUT = ROOT / 'docs' / 'evcharging_snapshot.json'


def main() -> None:
    table = ds.dataset(str(DATASET), format='parquet', partitioning='hive').to_table().to_pandas()
    table['ts'] = pd.to_datetime(table['ts'], utc=True)
    charging_cpos = cpos_with_charging(table)
    latest_ts = table['ts'].max()
    latest = table[table['ts'] == latest_ts].copy()

    latest['stato'] = latest['stato'].fillna('Sconosciuto')
    latest['stato_raw'] = latest['stato_raw'].fillna('UNKNOWN')
    latest['usage_observable'] = usage_observable(latest, charging_cpos)
    latest['is_autostrada'] = is_autostrada(latest['id_evse'], latest['cpo'], latest['indirizzo'])
    # Solo l'area configurata (mappa/tabella live) + autostrade siciliane
    # (caso a sé, restano visibili): le zone limitrofe che lo scraper
    # raccoglie comunque nel dataset grezzo non compaiono qui.
    is_comune = matches_area(latest['citta'], latest['cap'])
    latest = latest[is_comune | latest['is_autostrada']]

    active = int((latest['stato'] == 'Attivo').sum())
    inactive = int((latest['stato'] == 'Non Attivo').sum())
    charging = int((latest['stato_raw'] == 'CHARGING').sum())

    output = {
        'generated_at': latest_ts.isoformat(),
        'stats': {
            'total': int(len(latest)),
            'active': active,
            'inactive': inactive,
            'charging': charging,
        },
        'points': [
            {
                'id_evse': row['id_evse'],
                'stato': row['stato'],
                'stato_raw': row['stato_raw'],
                'real_time': bool(row['real_time']),
                'usage_observable': bool(row['usage_observable']),
                'cpo': row['cpo'],
                'indirizzo': row['indirizzo'],
                'citta': row['citta'],
                'cap': row['cap'],
                'lat': float(row['lat']),
                'lon': float(row['lon']),
                'potenza_w': int(row['potenza_w']) if pd.notna(row['potenza_w']) else None,
                'corrente': row['corrente'],
                'standard_connettore': row['standard_connettore'],
                'n_connettori': int(row['n_connettori']) if pd.notna(row['n_connettori']) else None,
                'open_24h7': bool(row['open_24h7']) if pd.notna(row['open_24h7']) else None,
                'party_id': row['party_id'],
                'is_autostrada': bool(row['is_autostrada']),
            }
            for _, row in latest.iterrows()
        ],
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
