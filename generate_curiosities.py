"""
generate_curiosities.py — Piccole curiosità calcolate sul dataset storico,
più: una classifica delle colonnine più USATE (filtrabile per fascia di
potenza lato frontend), una classifica delle più potenti, e un drill-down
delle 3 colonnine più usate per ciascun operatore.

Ogni curiosità testuale è una funzione indipendente che ritorna None se non
c'è ancora abbastanza storico per dirla in modo onesto (es. "ora di punta"
ha senso solo dopo qualche giorno, non dopo un singolo snapshot). Il JSON
contiene solo le curiosità "mature": niente placeholder per quelle mancanti,
la pagina mostra semplicemente quello che c'è.

Le classifiche non hanno una soglia sui giorni: basta che ci siano colonnine
candidate, e riportano sempre `days_collected` così la pagina può
dichiarare che è una classifica ancora giovane invece di nasconderla — a
differenza delle curiosità testuali sopra, un "primi risultati su N giorni"
resta onesto anche quando N è piccolo.

Solo le colonnine usage_observable entrano nei calcoli temporali sull'uso
(stesso motivo di generate_trends.py: real_time da solo non basta, vedi
usage_semantics.py). Le curiosità "statiche" (che fotografano
l'ultimo snapshot, es. quota AC/DC) non hanno questo vincolo. Tutte le
classifiche e i confronti sono limitati alle colonnine cittadine: le
autostrade sono un pubblico diverso (vedi generate_trends.py) e i loro DC
rapidi dominerebbero banalmente la classifica potenza travisandola da
curiosità cittadina.

Le autostrade siciliane configurate (A18/A19/A20/A29, vedi
docs/config.json -> confronto_autostrada) sono riconoscibili nel dataset
solo dove hanno un indirizzo/prefisso ID/nome CPO distinguibile, letto da
config.is_autostrada(): le colonnine che finiscono in `is_autostrada` sono
solo quelle delle aree di servizio effettivamente intercettate dallo
scraping (bbox/area configurata) — non "tutta la rete autostradale
siciliana". Un'autostrada priva di segnale riconoscibile nei dati (o un
gestore non ancora mappato) non comparirebbe affatto in questo confronto.

Va eseguito una volta al giorno, dopo generate_stats.py.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pyarrow.dataset as ds

from config import AREA_NOME, AUTOSTRADA_LABEL, is_autostrada, matches_area
from usage_semantics import cpos_with_charging, usage_observable

ROOT = Path(__file__).resolve().parent
DATASET = ROOT / 'data'
OUT = ROOT / 'docs' / 'stats' / 'data' / 'curiosities.json'
POI_PROXIMITY_FILE = ROOT / 'docs' / 'stats' / 'data' / 'poi_proximity.json'

WEEKDAY_LABELS = ['lunedì', 'martedì', 'mercoledì', 'giovedì', 'venerdì', 'sabato', 'domenica']

# Quante colonnine portare nella classifica d'uso: abbastanza da lasciare
# qualcosa dopo il filtro per fascia di potenza lato frontend, che mostra
# comunque solo le prime 3 del sottoinsieme filtrato.
CLASSIFICA_USO_MAX = 15

# Soglie minime di storico per le curiosità testuali che hanno bisogno di
# più giorni per non essere un abbaglio statistico su un singolo momento.
# Le classifiche non hanno una soglia sui giorni (vedi sopra).
MIN_DAYS_ORA_PUNTA = 3    # ora del giorno con più ricariche
MIN_DAYS_WEEKDAY = 7      # giorno della settimana con più ricariche


def power_tier(potenza_w) -> str | None:
    """Stesse soglie di generate_stats.py: bin su potenza_w, indipendenti
    da AC/DC (≤22 kW lenta, 22-50 kW rapida, >50 kW ultra-rapida)."""
    if pd.isna(potenza_w):
        return None
    w = float(potenza_w)
    if w <= 22000:
        return 'lenta'
    if w <= 50000:
        return 'rapida'
    return 'ultra'


def load_table() -> pd.DataFrame:
    table = ds.dataset(str(DATASET), format='parquet', partitioning='hive').to_table().to_pandas()
    table['ts'] = pd.to_datetime(table['ts'], utc=True)
    table['is_autostrada'] = is_autostrada(table['id_evse'], table['cpo'], table['indirizzo'])
    # Solo l'area configurata, non le zone limitrofe che lo scraper
    # raccoglie comunque nel dataset grezzo.
    table['is_comune'] = matches_area(table['citta'], table['cap'])
    table['is_active'] = table['stato'].eq('Attivo')
    table['is_charging'] = table['stato_raw'].fillna('').str.upper().eq('CHARGING')
    charging_cpos = cpos_with_charging(table)
    table['usage_observable'] = usage_observable(table, charging_cpos)
    return table


def fact_quota_ac_dc(latest: pd.DataFrame) -> dict | None:
    known = latest['corrente'].dropna()
    if known.empty:
        return None
    quota_dc = round((known == 'DC').mean() * 100, 1)
    return {
        'titolo': 'Corrente alternata o continua?',
        'testo': f'Il {quota_dc}% delle colonnine di {AREA_NOME} eroga corrente continua (DC, ricarica rapida); il resto è AC.',
    }


def fact_quota_real_time(latest: pd.DataFrame) -> dict | None:
    if latest.empty:
        return None
    quota = round(latest['real_time'].mean() * 100, 1)
    return {
        'titolo': 'Quanto è "live" lo stato che vedi',
        'testo': (
            f'Solo il {quota}% delle colonnine comunica lo stato in tempo reale: per le altre, '
            'il pallino verde o rosso che vedi è l\'ultima informazione statica pubblicata dal gestore.'
        ),
    }


def fact_citta_vs_autostrada(latest: pd.DataFrame) -> dict | None:
    """Confronto città/autostrada: compare solo se nel dataset del comune
    configurato ci sono anche colonnine autostradali rilevate (non è detto —
    dipende da quanto è vicino il comune alle autostrade configurate),
    altrimenti non è calcolabile e la curiosità viene omessa invece di
    essere scritta a mano.

    Il testo è esplicito sul fatto che non è "tutta la rete autostradale
    siciliana" ma solo le aree di servizio effettivamente rilevate qui, e
    che le autostrade configurate sono riconoscibili nei dati (indirizzo /
    prefisso ID / nome CPO in config.AUTOSTRADA) in un modo che non
    generalizza automaticamente ad altre autostrade con altri gestori —
    vedi nota di modulo più sopra."""
    citta = latest[latest['is_comune']]
    autostrada = latest[latest['is_autostrada']]
    if citta.empty or autostrada.empty:
        return None
    share_citta = round(citta['is_active'].mean() * 100, 1)
    share_autostrada = round(autostrada['is_active'].mean() * 100, 1)
    aree = sorted(autostrada['indirizzo'].dropna().unique())
    aree_label = ' e '.join(aree) if len(aree) <= 2 else f'{len(aree)} aree di servizio'
    return {
        'titolo': 'Città o autostrada?',
        'testo': (
            f'In questo momento il {share_citta}% delle colonnine di {AREA_NOME} è attivo, contro il '
            f'{share_autostrada}% di quelle rilevate su {aree_label} ({AUTOSTRADA_LABEL}): pubblici diversi, andamenti diversi. '
            'È un confronto possibile solo perché queste colonnine autostradali sono riconoscibili nei dati (operatore e/o indirizzo dedicati); '
            'colonnine di altre autostrade, con altri gestori, non lo sarebbero allo stesso modo.'
        ),
    }


def _classifica_per_colonnina(g: pd.DataFrame, max_items: int) -> list[dict]:
    """Classifica per quota di ricarica (uso reale, non disponibilità),
    con potenza/corrente allegate a ogni voce per il filtro lato client."""
    per_colonnina = g.groupby('id_evse').agg(
        share_charging=('is_charging', 'mean'),
        cpo=('cpo', 'first'),
        indirizzo=('indirizzo', 'first'),
        lat=('lat', 'first'),
        lon=('lon', 'first'),
        potenza_w=('potenza_w', 'first'),
        corrente=('corrente', 'first'),
    ).reset_index()
    if per_colonnina.empty:
        return []
    top = per_colonnina.sort_values('share_charging', ascending=False).head(max_items)
    return [
        {
            'rank': i + 1,
            'id_evse': row['id_evse'],
            'indirizzo': row['indirizzo'] or 'indirizzo sconosciuto',
            'cpo': row['cpo'] or 'operatore sconosciuto',
            'valore': f'{round(float(row["share_charging"]) * 100, 1)}% in ricarica',
            'lat': float(row['lat']),
            'lon': float(row['lon']),
            'potenza_w': None if pd.isna(row['potenza_w']) else int(row['potenza_w']),
            'corrente': row['corrente'],
            'fascia_potenza': power_tier(row['potenza_w']),
        }
        for i, (_, row) in enumerate(top.iterrows())
    ]


def classifica_uso(rt_city: pd.DataFrame, days: int) -> dict | None:
    """Colonnine più usate (quota di ricarica nel tempo), non solo le
    prime 3: il frontend filtra per fascia di potenza e mostra le prime 3
    del sottoinsieme filtrato. Nessuna soglia sui giorni — days_collected
    sempre a vista così anche 1 giorno solo resta dichiaratamente tale."""
    if rt_city.empty:
        return None
    items = _classifica_per_colonnina(rt_city, CLASSIFICA_USO_MAX)
    if not items:
        return None
    return {
        'titolo': 'Le colonnine più usate',
        'descrizione': f'Quota di tempo in ricarica, su {days} giorn{"o" if days == 1 else "i"} di storico raccolto.',
        'days_collected': days,
        'items': items,
    }


def per_operatore(rt_city: pd.DataFrame) -> dict:
    """Per ogni operatore con almeno una colonnina real-time cittadina, le
    sue 3 colonnine più usate. Operatori senza dati real-time (può
    succedere, come per le autostrade) non compaiono — non c'è nulla da mostrare."""
    result = {}
    for cpo, g in rt_city.groupby(rt_city['cpo'].fillna('Sconosciuto')):
        items = _classifica_per_colonnina(g, 3)
        if items:
            result[cpo] = {'items': items}
    return result


def top3_potenza(latest_city: pd.DataFrame) -> dict | None:
    """Le 3 colonnine con più potenza: dato statico dall'ultimo snapshot,
    nessuno storico richiesto."""
    known = latest_city[latest_city['potenza_w'].notna() & (latest_city['potenza_w'] > 0)]
    if known.empty:
        return None
    top = known.sort_values('potenza_w', ascending=False).head(3)
    return {
        'titolo': 'Le colonnine più potenti',
        'descrizione': 'Potenza massima del connettore principale, dall\'ultimo snapshot.',
        'items': [
            {
                'rank': i + 1,
                'id_evse': row['id_evse'],
                'indirizzo': row['indirizzo'] or 'indirizzo sconosciuto',
                'cpo': row['cpo'] or 'operatore sconosciuto',
                'valore': f'{round(float(row["potenza_w"]) / 1000, 1)} kW',
                'lat': float(row['lat']),
                'lon': float(row['lon']),
            }
            for i, (_, row) in enumerate(top.iterrows())
        ],
    }


def fact_ora_punta_ricarica(rt: pd.DataFrame, days: int) -> dict | None:
    if days < MIN_DAYS_ORA_PUNTA or rt.empty:
        return None
    per_ora = rt.groupby(rt['ts'].dt.hour)['is_charging'].mean()
    if per_ora.empty or per_ora.max() == 0:
        return None
    ora = int(per_ora.idxmax())
    quota = round(float(per_ora.max()) * 100, 1)
    return {
        'titolo': "L'ora di punta della ricarica",
        'testo': f'Fra le {ora}:00 e le {ora + 1}:00 la quota di colonnine in ricarica è mediamente più alta ({quota}%).',
    }


def fact_giorno_settimana_top(rt: pd.DataFrame, days: int) -> dict | None:
    if days < MIN_DAYS_WEEKDAY or rt.empty:
        return None
    per_giorno = rt.groupby(rt['ts'].dt.dayofweek)['is_charging'].mean()
    if per_giorno.empty or per_giorno.max() == 0:
        return None
    dow = int(per_giorno.idxmax())
    quota = round(float(per_giorno.max()) * 100, 1)
    return {
        'titolo': 'Il giorno con più ricariche',
        'testo': f'{WEEKDAY_LABELS[dow].capitalize()} è, in media, il giorno della settimana con più colonnine in ricarica ({quota}%).',
    }


POI_SINGOLARE = {
    'musei': 'un museo',
    'supermercati': 'un supermercato',
    'banche': 'una banca',
    'ospedali': 'un ospedale',
    'ambulatori': 'un ambulatorio',
}


def fact_poi_vicine() -> dict | None:
    """Legge poi_proximity.json (già calcolato da generate_poi_proximity.py,
    non ricalcola nulla qui) e ne fa una frase sulla categoria con quota
    più alta. None se il file non esiste ancora (fetch_poi.py non lanciato)."""
    if not POI_PROXIMITY_FILE.exists():
        return None
    try:
        data = json.loads(POI_PROXIMITY_FILE.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None
    categorie = data.get('categorie', {})
    if not categorie:
        return None
    top_key, top = max(categorie.items(), key=lambda kv: kv[1]['share'])
    soglia = data.get('soglia_metri', 300)
    singolare = POI_SINGOLARE.get(top_key, top['label'].lower())
    return {
        'titolo': 'Colonnine e città',
        'testo': f'Il {top["share"]}% delle colonnine cittadine si trova entro {soglia} m da {singolare}.',
    }


def main() -> None:
    table = load_table()
    if table.empty:
        print('dataset vuoto: curiosities.json non generato')
        return

    latest = table.sort_values('ts').drop_duplicates(subset=['id_evse'], keep='last')
    rt = table[table['usage_observable']].copy()
    rt_city = rt[rt['is_comune']]
    latest_city = latest[latest['is_comune']]
    days = int(rt['date'].nunique()) if not rt.empty else 0

    candidati = [
        fact_quota_ac_dc(latest),
        fact_quota_real_time(latest),
        fact_citta_vs_autostrada(latest),
        fact_ora_punta_ricarica(rt, days),
        fact_giorno_settimana_top(rt, days),
        fact_poi_vicine(),
    ]
    curiosita = [c for c in candidati if c is not None]

    top3 = {}
    uso = classifica_uso(rt_city, days)
    if uso:
        top3['uso'] = uso
    potenza = top3_potenza(latest_city)
    if potenza:
        top3['potenza'] = potenza

    payload = {
        'generated_at': pd.Timestamp.now('UTC').isoformat(),
        'days_collected': days,
        'curiosita': curiosita,
        'top3': top3,
        'per_operatore': per_operatore(rt_city),
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'generato {OUT} ({len(curiosita)} curiosità, top3: {sorted(top3.keys())}, '
          f'{len(payload["per_operatore"])} operatori con drill-down)')


if __name__ == '__main__':
    main()
