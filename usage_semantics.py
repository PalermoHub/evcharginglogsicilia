"""Quando l'occupazione (in uso / non in uso) di una colonnina è osservabile.

`real_time` (dalla PUN) dice solo se un operatore aggiorna lo stato Attivo/
Non Attivo dal vivo — non se distingue anche "in uso" da "libera". Alcuni
operatori real_time=True (verificato sullo storico completo: ACEA ENERGIA,
DUFERCO MOBILITY, Edison Next, Route220, TheF Cherging) non hanno mai
riportato altro che AVAILABLE/OUTOFORDER/INOPERATIVE/UNKNOWN, mai CHARGING.
Per loro lo stato Attivo è affidabile (sappiamo se è guasta), ma
l'occupazione resta ignota quanto per un operatore statico: vanno esclusi
dal denominatore "colonnine monitorabili" di ogni statistica sull'USO
(gauge, testo, trend, previsione, curiosità, sessioni), altrimenti gonfiano
il denominatore senza poter mai contribuire al numeratore.

`real_time` resta invece il criterio giusto per tutto ciò che riguarda solo
lo stato Attivo/Non Attivo (non l'uso): quello è comunque affidabile per
questi operatori.
"""
from __future__ import annotations

import pandas as pd


def cpos_with_charging(table: pd.DataFrame) -> set[str]:
    """CPO che hanno riportato almeno una volta stato_raw == 'CHARGING' nello
    storico. Va calcolato sull'intero storico raccolto (non sull'ultimo
    snapshot né su una finestra filtrata): un operatore charging-capable ma
    momentaneamente senza sessioni in corso nella finestra non deve
    risultare escluso per caso."""
    charging = table['stato_raw'].fillna('').str.upper() == 'CHARGING'
    return set(table.loc[charging, 'cpo'].dropna().unique())


def usage_observable(df: pd.DataFrame, charging_cpos: set[str]) -> pd.Series:
    """True se la colonnina è real_time E il suo operatore ha mai riportato
    CHARGING: solo in questo caso "Attivo" implica anche "sappiamo se è
    occupata", non solo "sappiamo se è guasta"."""
    return df['real_time'].fillna(False) & df['cpo'].fillna('').isin(charging_cpos)
