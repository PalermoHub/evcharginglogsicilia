"""
generate_station_usage.py — L'USO reale delle colonnine (non solo se
esistono/sono attive): sessioni di ricarica, fasce orarie più piene,
durata media, giorno record. Per singola colonnina (per il popup della
mappa) e aggregato città.

Solo il comune configurato (non i comuni limitrofi, non l'A22 — vedi
generate_trends.py per lo stesso criterio) e solo colonnine usage_observable
(vedi usage_semantics.py): per le altre lo stato è statico, o l'operatore
non distingue occupata da libera, e non esiste una "sessione" da rilevare.

Cos'è una sessione: una sequenza continua di rilevazioni con
stato_raw='CHARGING' per una colonnina, delimitata da rilevazioni non-
charging prima e dopo. La durata (fine - inizio) è per costruzione una
STIMA PER DIFETTO: la ricarica reale può essere iniziata in un punto
qualsiasi tra la rilevazione precedente (non-charging) e l'inizio
rilevato, e finita allo stesso modo dopo la fine rilevata — il limite è la
cadenza di polling, non un errore del calcolo. Le sessioni osservate con
una sola rilevazione contano nel numero di sessioni ma non entrano nella
durata media (durata non stimabile). La sessione eventualmente ancora in
corso all'ultima rilevazione non entra né nel conteggio né nella media.

L'energia (kWh) è una STIMA ulteriore rispetto alla durata: la PUN non
fornisce letture reali di energia, solo stato e potenza nominale del
connettore. La stima è durata_sessione × potenza_nominale, assumendo la
colonnina eroghi sempre alla sua potenza massima per tutta la sessione —
probabile sovrastima, soprattutto per la ricarica rapida DC dove la
potenza cala avvicinandosi al pieno. Non è una lettura reale, è un
indicatore di massima.

"Energia oggi" (energia_oggi_kwh, sia per colonnina che a livello città) è
calcolata sulle sessioni iniziate dalla mezzanotte di oggi in ora italiana
(Europe/Rome) in poi — a differenza delle altre finestre (ultima_ora,
ultime_24h, ...), che sono mobili e non di calendario.

Va eseguito una volta al giorno, dopo generate_stats.py.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pyarrow.dataset as ds

from config import AREA_NOME, matches_area
from usage_semantics import cpos_with_charging, usage_observable

ROOT = Path(__file__).resolve().parent
DATASET = ROOT / 'data'
OUT = ROOT / 'docs' / 'stations_usage.json'

MIN_ORE_PROFILO = 6     # ore distinte coperte minime per fidarsi del profilo orario
MIN_DAYS_WEEKDAY = 7    # giorni distinti minimi per il giorno-della-settimana più usato

# Stesse finestre mobili per energia e "veicoli serviti" (una sessione ≈ un
# veicolo). Mobili, non di calendario, così restano sempre significative
# indipendentemente dal giorno/ora in cui vengono generate.
FINESTRE = {
    'ultima_ora': pd.Timedelta(1, unit='h'),
    'ultime_24h': pd.Timedelta(24, unit='h'),
    'ultimi_7_giorni': pd.Timedelta(7, unit='D'),
    'ultimi_30_giorni': pd.Timedelta(30, unit='D'),
}

# Unica eccezione voluta alle finestre mobili qui sopra: "oggi" è di
# calendario (dalla mezzanotte di oggi, ora italiana, non ultime 24h),
# perché è quello che ci si aspetta leggendo "energia erogata oggi".
ROME_TZ = 'Europe/Rome'


def inizio_giornata_roma(now: pd.Timestamp) -> pd.Timestamp:
    """Mezzanotte di oggi in ora italiana (gestisce il cambio ora legale/
    solare), riportata in UTC per confrontarla con i timestamp del
    dataset."""
    return now.tz_convert(ROME_TZ).normalize().tz_convert('UTC')

WEEKDAY_LABELS = ['lunedì', 'martedì', 'mercoledì', 'giovedì', 'venerdì', 'sabato', 'domenica']

# Il ciclo nominale è ogni 5 minuti, ma lo scheduler di GitHub Actions non è
# affidabile su intervalli così brevi: nel dataset reale si osservano gap
# anche di ore fra una rilevazione e la successiva. Se lo stato è CHARGING
# prima e dopo un gap più largo di questo, NON si può assumere che la
# ricarica sia continuata per tutto il gap (potrebbe essere un'altra
# sessione, magari di un'altra auto) — meglio chiudere la sessione e
# aprirne una nuova, anche a costo di sottostimare qualche sessione lunga
# per davvero. Senza questo taglio, un gap di 3 ore letto come "sessione
# continua" a piena potenza gonfia enormemente durata ed energia stimate.
GAP_MASSIMO_MINUTI = 20


def load_usage_observable_city() -> pd.DataFrame:
    table = ds.dataset(str(DATASET), format='parquet', partitioning='hive').to_table().to_pandas()
    table['ts'] = pd.to_datetime(table['ts'], utc=True)
    charging_cpos = cpos_with_charging(table)
    table['usage_observable'] = usage_observable(table, charging_cpos)
    is_comune = matches_area(table['citta'], table['cap'])
    table = table[table['usage_observable'] & is_comune].copy()
    table['is_charging'] = table['stato_raw'].fillna('').str.upper().eq('CHARGING')
    return table


def detect_sessions(seq: list[tuple[pd.Timestamp, bool]]) -> tuple[list[dict], dict | None]:
    """seq: [(ts, is_charging), ...] ordinato per ts. Ritorna (sessioni
    chiuse, sessione in corso o None)."""
    sessions = []
    current = None
    max_gap = pd.Timedelta(GAP_MASSIMO_MINUTI, unit='m')
    for ts, charging in seq:
        if charging:
            if current is None:
                current = {'inizio': ts, 'fine': ts, 'n_rilevazioni': 1}
            elif ts - current['fine'] > max_gap:
                # Gap troppo largo per assumere ricarica continua: chiudo
                # questa sessione e ne apro una nuova da qui.
                sessions.append(current)
                current = {'inizio': ts, 'fine': ts, 'n_rilevazioni': 1}
            else:
                current['fine'] = ts
                current['n_rilevazioni'] += 1
        else:
            if current is not None:
                sessions.append(current)
                current = None
    return sessions, current


def durata_minuti(sess: dict) -> float:
    return (sess['fine'] - sess['inizio']).total_seconds() / 60.0


def profilo_orario(g: pd.DataFrame) -> list[dict] | None:
    ore_coperte = g['ts'].dt.hour.nunique()
    if ore_coperte < MIN_ORE_PROFILO:
        return None
    per_ora = g.groupby(g['ts'].dt.hour)['is_charging'].mean()
    return [
        {'ora': h, 'quota_charging': round(float(per_ora.get(h, 0.0)) * 100, 1)}
        for h in range(24)
    ]


def giorno_settimana_piu_usato(g: pd.DataFrame) -> dict | None:
    giorni_distinti = g['date'].nunique()
    if giorni_distinti < MIN_DAYS_WEEKDAY:
        return None
    per_giorno = g.groupby(g['ts'].dt.dayofweek)['is_charging'].mean()
    if per_giorno.empty or per_giorno.max() == 0:
        return None
    dow = int(per_giorno.idxmax())
    return {'giorno': WEEKDAY_LABELS[dow], 'quota_charging': round(float(per_giorno.max()) * 100, 1)}


def giorno_record(sessions: list[dict]) -> dict | None:
    """La data (non il giorno della settimana) con più minuti di ricarica
    totali nella sua storia. Una sessione viene attribuita interamente
    alla data del suo inizio."""
    if not sessions:
        return None
    per_data: dict[str, float] = {}
    for s in sessions:
        data = s['inizio'].strftime('%Y-%m-%d')
        per_data[data] = per_data.get(data, 0.0) + durata_minuti(s)
    data_top = max(per_data, key=per_data.get)
    return {'data': data_top, 'minuti_ricarica_totali': round(per_data[data_top], 1)}


def tag_energia(sessions: list[dict], potenza_w: float | None) -> None:
    """Aggiunge 'energia_kwh' a ogni sessione, in place. None se la potenza
    nominale della colonnina non è nota (nessuna stima possibile)."""
    for s in sessions:
        s['energia_kwh'] = round(durata_minuti(s) / 60.0 * potenza_w / 1000.0, 2) if potenza_w else None


def energy_summary(sessions: list[dict], now: pd.Timestamp, oggi_da: pd.Timestamp) -> dict:
    con_energia = [s for s in sessions if s.get('energia_kwh') is not None]
    out = {'totale_kwh_stimato': round(sum(s['energia_kwh'] for s in con_energia), 2)}
    for key, delta in FINESTRE.items():
        soglia = now - delta
        out[f'{key}_kwh'] = round(sum(s['energia_kwh'] for s in con_energia if s['inizio'] >= soglia), 2)
    out['oggi_kwh'] = round(sum(s['energia_kwh'] for s in con_energia if s['inizio'] >= oggi_da), 2)
    return out


def veicoli_serviti(sessions: list[dict], now: pd.Timestamp) -> dict:
    """Conteggio sessioni nelle stesse finestre mobili dell'energia — una
    sessione ≈ un veicolo che ha caricato in quella finestra. Sessioni con
    una sola rilevazione contano comunque (a differenza della durata media,
    qui basta sapere che una ricarica c'è stata, non per quanto)."""
    return {key: sum(1 for s in sessions if s['inizio'] >= now - delta) for key, delta in FINESTRE.items()}


def colonnina_top(stazioni: dict) -> dict | None:
    """La colonnina più USATA: energia stimata erogata come misura d'uso
    (combina durata e potenza, più informativa del solo conteggio sessioni)."""
    candidate = [
        {'id_evse': k, **v} for k, v in stazioni.items()
        if v.get('energia_totale_kwh_stimata')
    ]
    if not candidate:
        return None
    top = max(candidate, key=lambda s: s['energia_totale_kwh_stimata'])
    return {
        'id_evse': top['id_evse'],
        'indirizzo': top['indirizzo'],
        'cpo': top['cpo'],
        'n_sessioni': top['n_sessioni'],
        'energia_totale_kwh_stimata': top['energia_totale_kwh_stimata'],
        'lat': top['lat'],
        'lon': top['lon'],
    }


def operatori_per_uso(stazioni: dict, days_collected: int) -> list[dict]:
    """Tutti gli operatori con almeno una sessione osservata, con energia
    stimata erogata, numero di ricariche e media giornaliera di ricariche
    dall'inizio del monitoraggio (days_collected, stesso valore riportato a
    livello città). Non più limitata ai primi 5: la tabella "Operatori —
    ricariche" della pagina Statistiche mostra l'elenco completo (paginato
    lato frontend), qui serve la lista intera."""
    per_operatore: dict[str, dict] = {}
    for rec in stazioni.values():
        cpo = rec['cpo']
        o = per_operatore.setdefault(cpo, {'cpo': cpo, 'n_colonnine': 0, 'n_sessioni': 0, '_energia': 0.0})
        o['n_colonnine'] += 1
        o['n_sessioni'] += rec['n_sessioni']
        o['_energia'] += rec['energia_totale_kwh_stimata'] or 0.0

    lista = [
        {
            **{k: v for k, v in o.items() if k != '_energia'},
            'energia_totale_kwh_stimata': round(o['_energia'], 2),
            'media_sessioni_giornaliere': round(o['n_sessioni'] / days_collected, 2) if days_collected else None,
        }
        for o in per_operatore.values()
        if o['n_sessioni'] > 0
    ]
    # Ordine di default della tabella: n. ricariche desc, poi media
    # giornaliera desc, poi nome operatore asc (per questo il terzo campo
    # della chiave non è negato, a differenza dei primi due).
    lista.sort(key=lambda o: (-o['n_sessioni'], -(o['media_sessioni_giornaliere'] or 0), o['cpo']))
    return lista


def ultimo_uso(sessions: list[dict], ongoing: dict | None) -> str | None:
    """Fine dell'ultima sessione osservata (chiusa o ancora in corso): per
    il campo "ultimo uso" mostrato in tabella, non per le metriche di
    durata/energia (quelle restano sulle sole sessioni chiuse)."""
    candidati = [s['fine'] for s in sessions]
    if ongoing is not None:
        candidati.append(ongoing['fine'])
    return max(candidati).isoformat() if candidati else None


def session_metrics(sessions: list[dict]) -> dict:
    sessioni_stimabili = [s for s in sessions if s['n_rilevazioni'] >= 2]
    durata_media = (
        round(sum(durata_minuti(s) for s in sessioni_stimabili) / len(sessioni_stimabili), 1)
        if sessioni_stimabili else None
    )
    return {
        'n_sessioni': len(sessions),
        'durata_media_minuti': durata_media,
        'giorno_record': giorno_record(sessions),
    }


def main() -> None:
    table = load_usage_observable_city()
    if table.empty:
        print(f'nessuna colonnina con occupazione osservabile a {AREA_NOME} nel dataset: stations_usage.json non generato')
        return

    now = table['ts'].max()
    oggi_da = inizio_giornata_roma(now)
    stazioni = {}
    tutte_le_sessioni: list[dict] = []
    n_in_corso = 0
    for id_evse, g in table.sort_values('ts').groupby('id_evse'):
        g = g.sort_values('ts')
        seq = list(zip(g['ts'], g['is_charging']))
        sessions, ongoing = detect_sessions(seq)

        potenza_nota = g['potenza_w'].dropna()
        potenza_w = float(potenza_nota.iloc[-1]) if not potenza_nota.empty else None
        tag_energia(sessions, potenza_w)
        tutte_le_sessioni.extend(sessions)

        energia_stazione = [s['energia_kwh'] for s in sessions if s.get('energia_kwh') is not None]
        energia_oggi_stazione = [
            s['energia_kwh'] for s in sessions if s.get('energia_kwh') is not None and s['inizio'] >= oggi_da
        ]
        rec = {
            'n_osservazioni': int(len(g)),
            'profilo_orario': profilo_orario(g),
            'giorno_settimana_piu_usato': giorno_settimana_piu_usato(g),
            **session_metrics(sessions),
            'ultimo_uso': ultimo_uso(sessions, ongoing),
            'energia_totale_kwh_stimata': round(sum(energia_stazione), 2) if energia_stazione else None,
            'energia_oggi_kwh': round(sum(energia_oggi_stazione), 2) if energia_oggi_stazione else None,
            'veicoli_serviti': veicoli_serviti(sessions, now),
            'indirizzo': g['indirizzo'].iloc[-1] or 'indirizzo sconosciuto',
            'cpo': g['cpo'].iloc[-1] or 'operatore sconosciuto',
            'lat': float(g['lat'].iloc[-1]),
            'lon': float(g['lon'].iloc[-1]),
        }
        if ongoing is not None:
            n_in_corso += 1
            rec['sessione_in_corso'] = {
                'da': ongoing['inizio'].isoformat(),
                'minuti_finora': round(durata_minuti(ongoing), 1),
            }
        stazioni[id_evse] = rec

    # Città: profilo orario/settimanale sull'intera tabella (media sulla
    # flotta, corretto da flattare); le metriche di sessione invece
    # arrivano dalla lista aggregata delle sessioni per-colonnina, MAI da
    # detect_sessions sulla tabella flattata (mischierebbe le sequenze di
    # colonnine diverse creando sessioni false).
    # Giorni distinti coperti dallo storico cittadino con occupazione
    # osservabile: stesso calcolo di generate_trends.py, serve qui per la
    # media giornaliera di ricariche per operatore (n_sessioni / days_collected).
    days_collected = int(table['date'].nunique())

    city = {
        'n_osservazioni': int(len(table)),
        'n_colonnine_usage_observable': int(table['id_evse'].nunique()),
        'days_collected': days_collected,
        'profilo_orario': profilo_orario(table),
        'giorno_settimana_piu_usato': giorno_settimana_piu_usato(table),
        **session_metrics(tutte_le_sessioni),
        'n_sessioni_in_corso': n_in_corso,
        'energia': energy_summary(tutte_le_sessioni, now, oggi_da),
        'veicoli_serviti': veicoli_serviti(tutte_le_sessioni, now),
        'colonnina_top': colonnina_top(stazioni),
        'operatori_per_uso': operatori_per_uso(stazioni, days_collected),
    }

    payload = {
        'generated_at': pd.Timestamp.now('UTC').isoformat(),
        'nota': (
            'Le durate delle sessioni sono una stima per difetto, vincolata alla cadenza di '
            'polling: la ricarica reale può essere iniziata/finita in un punto qualsiasi tra '
            'due rilevazioni consecutive. L\'energia (kWh) è una stima ulteriore (durata × potenza '
            'nominale del connettore), non una lettura reale: probabile sovrastima, specie sulla '
            'ricarica rapida DC.'
        ),
        'city': city,
        'stazioni': stazioni,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    n_con_sessioni = sum(1 for s in stazioni.values() if s['n_sessioni'] > 0)
    print(f'generato {OUT} ({len(stazioni)} colonnine, {n_con_sessioni} con almeno una sessione, '
          f'{city["energia"]["totale_kwh_stimato"]} kWh stimati in totale)')


if __name__ == '__main__':
    main()
