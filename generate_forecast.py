"""
generate_forecast.py — Previsione della quota di colonnine cittadine in
ricarica, per i prossimi ORE_AVANTI ore.

Le colonnine dell'autostrada A22 sono escluse a monte (vedi
generate_trends.py per lo stesso ragionamento): pubblico di transito, non
urbano, e nessun operatore autostradale pubblica oggi lo stato in tempo
reale necessario per prevedere alcunché.

Modello (stesso principio di forecast.py in parklogtrento): profilo
stagionale giorno-settimana x ora, corretto con lo scostamento più recente,
con decadimento esponenziale della correzione nel tempo. L'errore storico
del profilo (MAE) diventa la banda min/max attorno alla stima.

Perché per l'aggregato città e non per singola colonnina (a differenza di
parklogtrento, che prevede per singola struttura): lo stato di una colonnina
è binario (in ricarica o no) ed è noisy a livello di singolo punto, e solo
una parte delle colonnine ha l'occupazione osservabile (usage_observable,
vedi usage_semantics.py: real_time non basta, serve un operatore che
distingua occupata da libera). Una previsione per singola colonnina sarebbe
poco più che rumore finché non c'è molto più storico; la quota aggregata è
la granularità onesta per iniziare.

Non emette nessuna previsione sotto MIN_GIORNI_STORICO giorni di storico
con occupazione osservabile: sotto soglia scrive solo {"available": false,
"days_collected", "days_needed"}.

Va eseguito una volta al giorno, dopo generate_trends.py.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

from config import AREA_NOME, matches_area
from usage_semantics import cpos_with_charging, usage_observable

ROOT = Path(__file__).resolve().parent
DATASET = ROOT / 'data'
OUT = ROOT / 'docs' / 'stats' / 'data' / 'forecast.json'

ORE_AVANTI = 48           # orizzonte della previsione
PESO_CORREZIONE = 0.6     # quanto pesa lo scostamento attuale
DECADIMENTO_ORE = 12.0    # dopo ~12h la correzione è svanita, resta il profilo
MIN_GIORNI_STORICO = 14   # sotto questa soglia non si prevede (dato insufficiente)


def load_usage_observable_city_table() -> pd.DataFrame:
    table = ds.dataset(str(DATASET), format='parquet', partitioning='hive').to_table().to_pandas()
    table['ts'] = pd.to_datetime(table['ts'], utc=True)
    charging_cpos = cpos_with_charging(table)
    table['usage_observable'] = usage_observable(table, charging_cpos)
    # Solo l'area configurata (non le zone limitrofe, non l'A22).
    is_comune = matches_area(table['citta'], table['cap'])
    table['is_charging'] = table['stato_raw'].fillna('').str.upper().eq('CHARGING')
    return table[table['usage_observable'] & is_comune].copy()


def serie_oraria(g: pd.DataFrame) -> pd.DataFrame:
    """Quota di colonnine in ricarica, mediata per ora piena."""
    h = g.groupby(g['ts'].dt.floor('h'))['is_charging'].mean().reset_index()
    h.columns = ['ts', 'share']
    h['share'] = h['share'] * 100.0
    h['dow'] = h['ts'].dt.dayofweek
    h['hour'] = h['ts'].dt.hour
    return h


def prevedi(g: pd.DataFrame) -> dict:
    days = int(g['date'].nunique()) if not g.empty else 0
    if days < MIN_GIORNI_STORICO:
        return {
            'available': False,
            'days_collected': days,
            'days_needed': MIN_GIORNI_STORICO,
        }

    h = serie_oraria(g)
    ultimo = h['ts'].max()
    profilo = h.groupby(['dow', 'hour'])['share'].mean()

    h = h.join(profilo.rename('prof'), on=['dow', 'hour'])
    h['res'] = h['share'] - h['prof']
    mae = float(h['res'].abs().mean())

    ultima_oss = h.sort_values('ts').iloc[-1]
    eta_ore = (ultimo - ultima_oss['ts']).total_seconds() / 3600.0
    scarto = float(ultima_oss['res']) if eta_ore <= 3 and not pd.isna(ultima_oss['res']) else 0.0

    punti = []
    for k in range(1, ORE_AVANTI + 1):
        t = ultimo + pd.Timedelta(k, unit='h')
        key = (t.dayofweek, t.hour)
        if key not in profilo.index:
            continue
        base = float(profilo.loc[key])
        peso = PESO_CORREZIONE * float(np.exp(-k / DECADIMENTO_ORE))
        stima = base + peso * scarto
        stima = max(0.0, min(100.0, stima))
        punti.append({
            'ts': t.strftime('%Y-%m-%dT%H:00'),
            'share_charging': round(stima, 1),
            'min': round(max(0.0, stima - mae), 1),
            'max': round(min(100.0, stima + mae), 1),
        })

    return {
        'available': True,
        'days_collected': days,
        'mae_storico': round(mae, 1),
        'scarto_attuale': round(scarto, 1),
        'orizzonte_ore': ORE_AVANTI,
        'punti': punti,
    }


def main() -> None:
    g = load_usage_observable_city_table()

    payload = {
        'generated_at': pd.Timestamp.now('UTC').isoformat(),
        'label': f'{AREA_NOME} città',
        'modello': 'profilo giorno-settimana x ora, corretto con lo scostamento più recente',
        'nota': (
            'Previsione sperimentale e non ufficiale. La fonte dei dati è la PUN (GSE/MASE), '
            'la previsione no. Sotto i 14 giorni di storico non viene emessa.'
        ),
        **prevedi(g),
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print('generato', OUT)


if __name__ == '__main__':
    main()
