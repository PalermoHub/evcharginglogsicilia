from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd
import pyarrow.dataset as ds

from config import is_autostrada, matches_area
from usage_semantics import cpos_with_charging, usage_observable

ROOT = Path(__file__).resolve().parent
DATASET = ROOT / 'data'
OUT_DIR = ROOT / 'docs' / 'stats' / 'data'

POI_PATTERNS = {
    'Poli': [r'\bpoli\b'],
    'Casse Rurali': [r'\bcassa rurale\b', r'\bcasse rurali\b'],
    'Supermercati': [r'\bsupermercato\b', r'\bcoop\b', r'\bconad\b'],
    'Stazioni ferroviarie': [r'\bstazione\b', r'\bfs\b'],
}

# Fasce di potenza (bin su potenza_w, indipendenti da AC/DC): usate sia per
# la statistica operatori qui sotto, sia per il filtro sulla classifica
# d'uso in generate_curiosities.py — stesse soglie in entrambi gli script.
def power_tier(potenza_w) -> str | None:
    if pd.isna(potenza_w):
        return None
    w = float(potenza_w)
    if w <= 22000:
        return 'lenta'
    if w <= 50000:
        return 'rapida'
    return 'ultra'


def classify_status(row):
    raw = str(row['stato_raw']).strip().upper()
    if raw == 'CHARGING':
        return 'In ricarica'

    state = str(row['stato']).strip()
    if state == 'Attivo':
        return 'Attivo'
    if state == 'Non Attivo':
        return 'Non Attivo'
    return 'Sconosciuto'


def contains_any(text: str, patterns):
    lower = text.lower()
    return any(re.search(pattern, lower) for pattern in patterns)


def build_operators(city_only: pd.DataFrame) -> list[dict]:
    """Operatori cittadini (A22 escluse, ha già la sua sezione a parte),
    con conteggio per fascia di potenza per il filtro lato frontend.
    Ordinata per numero di colonnine desc: i primi 3 elementi SONO la
    'top 3 operatori', nessun campo duplicato."""
    df = city_only.copy()
    df['cpo_norm'] = df['cpo'].fillna('Sconosciuto')
    df['tier'] = df['potenza_w'].apply(power_tier)

    rows = []
    for name, g in df.groupby('cpo_norm'):
        tier_counts = g['tier'].value_counts()
        rows.append({
            'name': name,
            'count': int(len(g)),
            'active': int(g['is_active'].sum()),
            'active_known': int(g['is_active_known'].sum()),
            'active_unknown': int(g['is_active_unknown'].sum()),
            'by_power': {
                'lenta': int(tier_counts.get('lenta', 0)),
                'rapida': int(tier_counts.get('rapida', 0)),
                'ultra': int(tier_counts.get('ultra', 0)),
            },
        })
    rows.sort(key=lambda r: r['count'], reverse=True)
    return rows[:10]


def build_stats_payload(table: pd.DataFrame, latest: pd.DataFrame):
    latest = latest.copy()
    latest['status'] = latest.apply(classify_status, axis=1)
    latest['is_active'] = latest['status'].eq('Attivo')
    latest['is_inactive'] = latest['status'].eq('Non Attivo')
    latest['is_charging'] = latest['status'].eq('In ricarica')
    # 'Attivo' copre sia colonnine il cui operatore distingue davvero
    # occupata/libera (usage_observable, vedi usage_semantics.py) sia
    # colonnine il cui stato è un'assunzione (real_time=False, o
    # real_time=True ma l'operatore non ha mai riportato CHARGING): is_active
    # da solo confonde le due cose, quindi si separa qui una volta per
    # tutte e si riusa ovunque sotto (summary, operatori, POI).
    charging_cpos = cpos_with_charging(table)
    latest['usage_observable'] = usage_observable(latest, charging_cpos)
    latest['is_active_known'] = latest['is_active'] & latest['usage_observable']
    latest['is_active_unknown'] = latest['is_active'] & ~latest['usage_observable']

    is_a22 = is_autostrada(latest['id_evse'], latest['cpo'], latest['indirizzo'])
    latest['is_a22'] = is_a22
    # Solo l'area configurata (comune o regione, vedi config.matches_area):
    # non le zone limitrofe che lo scraper raccoglie comunque nel dataset
    # grezzo (bbox di discovery volutamente larga), e non l'A22 (pubblico
    # diverso, sezione a parte più sotto).
    is_comune = matches_area(latest['citta'], latest['cap'])
    city_only = latest[is_comune & ~is_a22]

    summary = {
        'total': int(len(city_only)),
        'active': int(city_only['is_active'].sum()),
        'active_known': int(city_only['is_active_known'].sum()),
        'active_unknown': int(city_only['is_active_unknown'].sum()),
        'inactive': int(city_only['is_inactive'].sum()),
        'charging': int(city_only['is_charging'].sum()),
        'share_active': round(city_only['is_active'].mean() * 100, 1) if len(city_only) else 0,
        'generated_at': latest['ts'].max().isoformat(),
        # Prima rilevazione in assoluto nel dataset grezzo (non filtrata per
        # città/A22): dà il contesto — da quanti giorni raccogliamo dati —
        # a tutte le statistiche della pagina, non solo a questo summary.
        'raccolta_dati_dal': table['ts'].min().isoformat(),
    }

    a22_df = latest[is_a22]
    a22 = {
        'count': int(len(a22_df)),
        'active': int(a22_df['is_active'].sum()),
        'inactive': int(a22_df['is_inactive'].sum()),
        'charging': int(a22_df['is_charging'].sum()),
        'share_active': round(a22_df['is_active'].mean() * 100, 1) if len(a22_df) else 0,
        'operators': a22_df['cpo'].value_counts().head(5).to_dict(),
    }

    poi_rows = []
    for poi_name, patterns in POI_PATTERNS.items():
        poi_df = city_only[
            city_only['indirizzo'].fillna('').apply(lambda x: contains_any(str(x), patterns))
            | city_only['cpo'].fillna('').apply(lambda x: contains_any(str(x), patterns))
        ]
        if poi_df.empty:
            continue
        poi_rows.append({
            'name': poi_name,
            'count': int(len(poi_df)),
            'active': int(poi_df['is_active'].sum()),
            'active_known': int(poi_df['is_active_known'].sum()),
            'active_unknown': int(poi_df['is_active_unknown'].sum()),
            'inactive': int(poi_df['is_inactive'].sum()),
            'charging': int(poi_df['is_charging'].sum()),
            'share_active': round(poi_df['is_active'].mean() * 100, 1),
        })

    operators = build_operators(city_only)

    return {
        'summary': summary,
        'a22': a22,
        'pois': poi_rows,
        'operators': operators,
    }


def main() -> None:
    table = ds.dataset(str(DATASET), format='parquet', partitioning='hive').to_table().to_pandas()
    table['ts'] = pd.to_datetime(table['ts'], utc=True)
    latest = table.sort_values('ts').drop_duplicates(subset=['id_evse'], keep='last')
    payload = build_stats_payload(table, latest)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / 'stats.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print('generated', OUT_DIR / 'stats.json')


if __name__ == '__main__':
    main()
