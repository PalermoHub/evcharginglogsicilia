#!/usr/bin/env python3
"""
fetch_poi.py — Scarica una tantum i punti di interesse (musei, supermercati,
banche, ospedali, ambulatori) nell'area configurata (docs/config.json) da
OpenStreetMap, via Overpass API, e li salva in poi_<area>.json.

Perché non da dati.trentino.it: il dataset comunale "Luoghi e punti di
interesse del Comune di Trento" non è più raggiungibile (404), e l'unico
dataset provinciale attivo ("Punti di interesse del Trentino") è un elenco
turistico del 2013 (hotel/ristoranti), non aggiornato e privo delle
categorie che servono qui. Per altre aree non esiste comunque un equivalente
generico, quindi si usa sempre OSM/Overpass.

Su un'area grande (es. un'intera regione, non un comune) la bbox viene
spezzata in una griglia di sotto-query (vedi _split_bbox): Overpass è un
servizio pubblico condiviso con limiti su dimensione/tempo di una singola
query, una bbox larga quanto la Sicilia in una sola richiesta rischia il
timeout. Su un comune la griglia collassa a una sola tile (bbox intera,
comportamento identico a prima).

Script MANUALE, da rilanciare a mano ogni tanto: non va interrogato
automaticamente ad ogni build (per questo non è nei workflow GitHub
Actions). I punti di interesse cambiano comunque di rado.

Licenza dei dati risultanti: OpenStreetMap, © contributori OpenStreetMap,
ODbL — l'attribuzione va mantenuta (vedi docs/info/index.html).

Uso:
  python fetch_poi.py
"""
from __future__ import annotations

import json
import math
import time

import requests

from config import BBOX as CONFIG_BBOX, POI_FILE as OUT

OVERPASS_URL = 'https://overpass-api.de/api/interpreter'
TIMEOUT = 90
# Il reverse proxy davanti a Overpass rifiuta con 406 lo User-Agent di
# default di `requests` (probabile filtro anti-bot generico); un
# User-Agent "da browser/curl" basta a farlo accettare.
HEADERS = {'User-Agent': 'curl/8.5.0'}

if not CONFIG_BBOX:
    raise SystemExit('docs/config.json non ha "bbox": necessaria per fetch_poi.py')

# Oltre questa estensione (gradi) la bbox viene spezzata in una griglia di
# sotto-bbox (vedi _split_bbox) invece di essere interrogata in un colpo
# solo. ~2° è già abbondante per un singolo comune (tile unica), una
# regione grande come la Sicilia (~3.7° x 3.9°) finisce spezzata in più tile.
MAX_TILE_DEG = 2.0

# categoria -> lista di filtri Overpass (chiave, valore)
CATEGORIES: dict[str, list[tuple[str, str]]] = {
    'musei': [('tourism', 'museum')],
    'supermercati': [('shop', 'supermarket')],
    'banche': [('amenity', 'bank')],
    'ospedali': [('amenity', 'hospital')],
    'ambulatori': [('amenity', 'clinic'), ('amenity', 'doctors')],
}

# Categorie "incrocio": non hanno un nome proprio in OSM (i nodi
# motorway_junction/traffic_signals raramente hanno un tag `name`), quindi
# il nome mostrato è quello della via su cui si trovano, con prefisso
# "Incrocio " — vedi fetch_road_junctions().
# categoria -> (valori highway delle way "genitore", valori highway dei nodi da cercare su quelle way)
JUNCTION_CATEGORIES: dict[str, tuple[list[str], list[str]]] = {
    'svincoli_autostradali': (['motorway'], ['motorway_junction']),
    'incroci_primarie': (['trunk', 'primary'], ['motorway_junction', 'traffic_signals']),
}


def _split_bbox(bbox: tuple[float, float, float, float], max_tile_deg: float = MAX_TILE_DEG):
    """bbox = (lat_min, lat_max, lon_min, lon_max) -> lista di sotto-bbox
    nello stesso formato, a griglia regolare, ciascuna entro max_tile_deg
    di lato. Una bbox già piccola (un comune) resta in un'unica tile."""
    lat_min, lat_max, lon_min, lon_max = bbox
    lat_span, lon_span = lat_max - lat_min, lon_max - lon_min
    n_lat = max(1, math.ceil(lat_span / max_tile_deg))
    n_lon = max(1, math.ceil(lon_span / max_tile_deg))
    tiles = []
    for i in range(n_lat):
        for j in range(n_lon):
            tiles.append((
                lat_min + i * lat_span / n_lat,
                lat_min + (i + 1) * lat_span / n_lat,
                lon_min + j * lon_span / n_lon,
                lon_min + (j + 1) * lon_span / n_lon,
            ))
    return tiles


def element_point(el: dict) -> tuple[float, float] | None:
    if el.get('type') == 'node':
        return el.get('lat'), el.get('lon')
    center = el.get('center')
    if center:
        return center.get('lat'), center.get('lon')
    return None


def _run_overpass_query(cat_name: str, query: str) -> list[dict]:
    # Backoff esponenziale (15s, 30s, 60s, 120s, 240s): su un'area grande
    # (più tile) il servizio pubblico risponde spesso 429 (rate limit) o
    # 504 (timeout lato loro su query pesanti) — un retry fisso a 10s si
    # esaurisce troppo in fretta contro un rate limiter, qui si dà più
    # margine invece di arrendersi dopo 3 tentativi ravvicinati. Stesso
    # backoff anche per errori di rete locali/transitori (connessione
    # caduta, DNS, timeout socket): non solo risposte HTTP del server.
    max_attempts = 5
    r = None
    for attempt in range(max_attempts):
        try:
            r = requests.post(OVERPASS_URL, data={'data': query}, timeout=TIMEOUT + 10, headers=HEADERS)
            if r.status_code == 200:
                break
            reason = str(r.status_code)
        except requests.exceptions.RequestException as e:
            r = None
            reason = f'errore di rete: {e.__class__.__name__}'
        wait = 15 * (2 ** attempt)
        print(f'  {cat_name}: tentativo {attempt + 1}/{max_attempts} fallito ({reason}), riprovo fra {wait}s...')
        time.sleep(wait)
    else:
        if r is not None:
            r.raise_for_status()
        raise requests.exceptions.ConnectionError(f'{cat_name}: rete irraggiungibile dopo {max_attempts} tentativi')
    return r.json().get('elements', [])


def fetch_category(cat_name: str, filters: list[tuple[str, str]],
                    bbox: tuple[float, float, float, float]) -> list[dict]:
    lat_min, lat_max, lon_min, lon_max = bbox
    bbox_str = f'{lat_min},{lon_min},{lat_max},{lon_max}'
    clauses = []
    for key, value in filters:
        clauses.append(f'node["{key}"="{value}"]({bbox_str});')
        clauses.append(f'way["{key}"="{value}"]({bbox_str});')
    query = f'[out:json][timeout:{TIMEOUT}];\n(\n  {"".join(clauses)}\n);\nout center tags;'

    elements = _run_overpass_query(cat_name, query)
    items = []
    for el in elements:
        tags = el.get('tags', {}) or {}
        point = element_point(el)
        if not point or point[0] is None or point[1] is None:
            continue
        lat, lon = round(float(point[0]), 6), round(float(point[1]), 6)
        name = tags.get('name') or tags.get('name:it') or 'Senza nome'
        items.append({'name': name, 'lat': lat, 'lon': lon})
    return items


def fetch_road_junctions(cat_name: str, way_highway_values: list[str], node_highway_values: list[str],
                          bbox: tuple[float, float, float, float]) -> list[dict]:
    """Nodi highway=motorway_junction/traffic_signals che giacciono su way
    highway=motorway/trunk/primary, col nome preso dalla way (i nodi stessi
    di rado hanno un `name`). Una query sola: chiede sia le way (per i tag
    name/ref e l'elenco dei nodi che le compongono) sia i nodi filtrati che
    ne fanno parte, poi il match nodo->via è fatto in Python via l'elenco
    `nodes` di ogni way."""
    lat_min, lat_max, lon_min, lon_max = bbox
    bbox_str = f'{lat_min},{lon_min},{lat_max},{lon_max}'
    way_re = '|'.join(way_highway_values)
    node_re = '|'.join(node_highway_values)
    query = (
        f'[out:json][timeout:{TIMEOUT}];\n'
        f'way["highway"~"^({way_re})$"]({bbox_str})->.w;\n'
        f'node(w.w)["highway"~"^({node_re})$"]->.n;\n'
        f'(.w; .n;);\n'
        f'out body;'
    )
    elements = _run_overpass_query(cat_name, query)

    ways = [el for el in elements if el.get('type') == 'way']
    nodes = {el['id']: el for el in elements if el.get('type') == 'node'}

    node_to_way_tags: dict[int, dict] = {}
    for way in ways:
        way_tags = way.get('tags', {}) or {}
        for node_id in way.get('nodes', []):
            if node_id in nodes and node_id not in node_to_way_tags:
                node_to_way_tags[node_id] = way_tags

    items = []
    for node_id, node in nodes.items():
        lat, lon = node.get('lat'), node.get('lon')
        if lat is None or lon is None:
            continue
        way_tags = node_to_way_tags.get(node_id, {})
        nome_via = way_tags.get('name') or way_tags.get('ref') or 'via senza nome'
        items.append({'name': f'Incrocio {nome_via}', 'lat': round(float(lat), 6), 'lon': round(float(lon), 6)})
    return items


def _dedup(items: list[dict]) -> list[dict]:
    """Le tile della griglia si toccano ai bordi: un elemento vicino al
    confine può risultare in due query. Stessa coppia di coordinate
    arrotondate + stesso nome => stesso elemento OSM, si tiene una copia."""
    seen = set()
    out = []
    for item in items:
        key = (item['name'], item['lat'], item['lon'])
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def fetch() -> dict:
    tiles = _split_bbox(CONFIG_BBOX)
    if len(tiles) > 1:
        print(f'bbox spezzata in {len(tiles)} tile (area larga)')

    incomplete: list[str] = []

    categories: dict[str, list[dict]] = {}
    for cat_name, filters in CATEGORIES.items():
        print(f'interrogo Overpass per "{cat_name}"...')
        items = []
        for i, tile in enumerate(tiles):
            try:
                items.extend(fetch_category(cat_name, filters, tile))
            except requests.exceptions.RequestException as e:
                print(f'  {cat_name}: tile {i + 1}/{len(tiles)} fallita anche dopo tutti i tentativi ({e}), salto e continuo')
                incomplete.append(f'{cat_name} (tile {i + 1}/{len(tiles)})')
            time.sleep(5)  # non martellare un servizio pubblico condiviso
        categories[cat_name] = _dedup(items)
        print(f'  {cat_name}: {len(categories[cat_name])} elementi')
    for cat_name, (way_values, node_values) in JUNCTION_CATEGORIES.items():
        print(f'interrogo Overpass per "{cat_name}"...')
        items = []
        for i, tile in enumerate(tiles):
            try:
                items.extend(fetch_road_junctions(cat_name, way_values, node_values, tile))
            except requests.exceptions.RequestException as e:
                print(f'  {cat_name}: tile {i + 1}/{len(tiles)} fallita anche dopo tutti i tentativi ({e}), salto e continuo')
                incomplete.append(f'{cat_name} (tile {i + 1}/{len(tiles)})')
            time.sleep(5)
        categories[cat_name] = _dedup(items)
        print(f'  {cat_name}: {len(categories[cat_name])} elementi')

    if incomplete:
        print(f'\nATTENZIONE: {len(incomplete)} tile non recuperate (Overpass persistentemente in errore), dati parziali per: {", ".join(incomplete)}')
        print('Rilanciare fetch_poi.py più tardi per completare (sovrascrive il file con un nuovo tentativo completo).')

    return categories


def main() -> None:
    categories = fetch()
    payload = {
        'generated_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'source': 'OpenStreetMap contributors, via Overpass API (ODbL)',
        'bbox': list(CONFIG_BBOX),
        'categories': categories,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    for name, items in categories.items():
        print(f'  {name}: {len(items)}')
    print('scritto', OUT)


if __name__ == '__main__':
    main()
