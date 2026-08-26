#!/usr/bin/env python3
"""
extract_poi_offline.py — Estrae musei, supermercati, banche, ospedali,
ambulatori, svincoli autostradali e incroci di strade primarie da un
estratto locale di OpenStreetMap in formato GeoPackage (es. osm/*.gpkg),
invece di interrogare Overpass (fetch_poi.py).

Perché non fetch_poi.py: su un'area larga come la Sicilia, Overpass va
interrogato a tile (vedi _split_bbox lì) con backoff fra un tentativo e
l'altro — praticabile ma lento (ore) e dipendente dalla disponibilità del
servizio pubblico. Un estratto regionale locale (GeoPackage, es. da
Geofabrik) contiene già tutti i dati e la query è istantanea.

Schema atteso del GeoPackage: quello standard del driver OSM di GDAL
(layer "points/lines/multilinestrings/multipolygons/other_relations").
I tag comuni (amenity, shop, tourism...) sono colonne dirette su
"multipolygons" (aree/relazioni) ma su "points" (nodi) finiscono tutti
nella colonna "other_tags", una stringa hstore-like
`"chiave"=>"valore","chiave2"=>"valore2"` — vedi _other_tag().

Stesso output di fetch_poi.py: poi_<area>.json (config.POI_FILE), stessa
bbox di docs/config.json, stesse categorie/etichette lette da
generate_poi_proximity.py/generate_poi_usage.py.

Le "incroci" (svincoli_autostradali, incroci_primarie) non hanno un nome
proprio in OSM: si prende il nome/ref della way (motorway/trunk/primary)
di cui il nodo incrocio è un vertice, appaiando nodo e way per coordinate
esatte (stesso identico punto, essendo lo stesso nodo OSM condiviso) —
replica in locale il join che fetch_road_junctions() fa via Overpass con
`node(w.w)`.

Script MANUALE, usa-e-getta come fetch_poi.py: da rilanciare a mano
quando serve un nuovo estratto, non nei workflow GitHub Actions.

Licenza dei dati risultanti: OpenStreetMap, © contributori OpenStreetMap,
ODbL — l'attribuzione va mantenuta (vedi docs/info/index.html).

Uso:
  python extract_poi_offline.py osm/19_Sicilia-2026-08-25T11Z.gpkg
"""
from __future__ import annotations

import json
import re
import sys
import time
import unicodedata
from pathlib import Path

from osgeo import ogr

ogr.UseExceptions()

# Letto direttamente da docs/config.json invece che da config.py: config.py
# importa pandas (per matches_area/is_autostrada, qui non usate) e questo
# script deve girare anche dove pandas non è installato.
ROOT = Path(__file__).resolve().parent
_config = json.loads((ROOT / 'docs' / 'config.json').read_text(encoding='utf-8'))
CONFIG_BBOX = tuple(_config['bbox']) if 'bbox' in _config else None
_AREA_NOME = _config.get('area_nome') or _config.get('comune')


def _slug(name: str) -> str:
    s = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode('ascii')
    return ''.join(c if c.isalnum() else '_' for c in s.strip().lower()).strip('_')


if not CONFIG_BBOX:
    raise SystemExit('docs/config.json non ha "bbox": necessaria per extract_poi_offline.py')
if not _AREA_NOME:
    raise SystemExit('docs/config.json non ha "area_nome" né "comune"')

OUT = ROOT / f'poi_{_slug(_AREA_NOME)}.json'
LAT_MIN, LAT_MAX, LON_MIN, LON_MAX = CONFIG_BBOX

# categoria -> lista di filtri (chiave, valore) — stessa mappa di fetch_poi.py
CATEGORIES: dict[str, list[tuple[str, str]]] = {
    'musei': [('tourism', 'museum')],
    'supermercati': [('shop', 'supermarket')],
    'banche': [('amenity', 'bank')],
    'ospedali': [('amenity', 'hospital')],
    'ambulatori': [('amenity', 'clinic'), ('amenity', 'doctors')],
}

# categoria -> (valori highway delle way "genitore", valori highway dei nodi da cercare su quelle way)
JUNCTION_CATEGORIES: dict[str, tuple[list[str], list[str]]] = {
    'svincoli_autostradali': (['motorway'], ['motorway_junction']),
    'incroci_primarie': (['trunk', 'primary'], ['motorway_junction', 'traffic_signals']),
}

# Cattura "chiave"=>"valore" nella colonna other_tags del driver OSM di GDAL,
# con `"` e `\` interni sfuggiti da `\`.
_TAG_RE = re.compile(r'"((?:[^"\\]|\\.)*)"=>"((?:[^"\\]|\\.)*)"')


def _other_tag(other_tags: str | None, key: str) -> str | None:
    if not other_tags:
        return None
    for k, v in _TAG_RE.findall(other_tags):
        if k == key:
            return v.replace('\\"', '"').replace('\\\\', '\\')
    return None


def _in_bbox(lat: float, lon: float) -> bool:
    return LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX


def _name_of(name: str | None, other_tags: str | None) -> str:
    return name or _other_tag(other_tags, 'name:it') or 'Senza nome'


def _dedup(items: list[dict]) -> list[dict]:
    """Un punto reale può comparire sia come nodo sia come area con lo
    stesso nome/posizione (es. mappato due volte): stessa tripla
    nome+lat+lon => stesso elemento, si tiene una copia (come fetch_poi.py)."""
    seen = set()
    out = []
    for item in items:
        key = (item['name'], item['lat'], item['lon'])
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def fetch_category(ds, filters: list[tuple[str, str]]) -> list[dict]:
    items: list[dict] = []

    # Nodi: i tag comuni non sono colonne dirette, filtro via LIKE su other_tags.
    points = ds.GetLayerByName('points')
    points.SetAttributeFilter(
        ' OR '.join(f'''other_tags LIKE '%"{key}"=>"{value}"%\'''' for key, value in filters)
    )
    for f in points:
        geom = f.GetGeometryRef()
        if geom is None:
            continue
        lon, lat = geom.GetX(), geom.GetY()
        if not _in_bbox(lat, lon):
            continue
        items.append({
            'name': _name_of(f.GetField('name'), f.GetField('other_tags')),
            'lat': round(lat, 6),
            'lon': round(lon, 6),
        })

    # Way/relation (aree): gli stessi tag SONO colonne dirette su multipolygons.
    polys = ds.GetLayerByName('multipolygons')
    key = filters[0][0]  # tutti i filtri di una categoria condividono la stessa chiave
    polys.SetAttributeFilter(' OR '.join(f"{key} = '{value}'" for _, value in filters))
    for f in polys:
        geom = f.GetGeometryRef()
        if geom is None or geom.IsEmpty():
            continue
        try:
            centroid = geom.Centroid()
        except Exception:
            continue
        lon, lat = centroid.GetX(), centroid.GetY()
        if not _in_bbox(lat, lon):
            continue
        items.append({
            'name': _name_of(f.GetField('name'), f.GetField('other_tags')),
            'lat': round(lat, 6),
            'lon': round(lon, 6),
        })

    return _dedup(items)


def fetch_junctions(ds, way_highway_values: list[str], node_highway_values: list[str]) -> list[dict]:
    lines = ds.GetLayerByName('lines')
    lines.SetAttributeFilter(' OR '.join(f"highway = '{v}'" for v in way_highway_values))
    vertex_tags: dict[tuple[float, float], dict] = {}
    for f in lines:
        geom = f.GetGeometryRef()
        if geom is None:
            continue
        tags = {'name': f.GetField('name'), 'ref': _other_tag(f.GetField('other_tags'), 'ref')}
        for i in range(geom.GetPointCount()):
            x, y = geom.GetPoint(i)[0], geom.GetPoint(i)[1]
            vertex_tags.setdefault((round(x, 7), round(y, 7)), tags)

    points = ds.GetLayerByName('points')
    points.SetAttributeFilter(' OR '.join(f"highway = '{v}'" for v in node_highway_values))
    items = []
    for f in points:
        geom = f.GetGeometryRef()
        if geom is None:
            continue
        lon, lat = geom.GetX(), geom.GetY()
        tags = vertex_tags.get((round(lon, 7), round(lat, 7)))
        if tags is None:
            continue  # nodo non su una way del tipo richiesto
        if not _in_bbox(lat, lon):
            continue
        nome_via = tags['name'] or tags['ref'] or 'via senza nome'
        items.append({'name': f'Incrocio {nome_via}', 'lat': round(lat, 6), 'lon': round(lon, 6)})

    return _dedup(items)


def fetch(gpkg_path: str) -> dict:
    ds = ogr.Open(gpkg_path)
    if ds is None:
        raise SystemExit(f'impossibile aprire {gpkg_path}')

    categories: dict[str, list[dict]] = {}
    for cat_name, filters in CATEGORIES.items():
        print(f'estraggo "{cat_name}" da {gpkg_path}...')
        categories[cat_name] = fetch_category(ds, filters)
        print(f'  {cat_name}: {len(categories[cat_name])} elementi')

    for cat_name, (way_values, node_values) in JUNCTION_CATEGORIES.items():
        print(f'estraggo "{cat_name}" da {gpkg_path}...')
        categories[cat_name] = fetch_junctions(ds, way_values, node_values)
        print(f'  {cat_name}: {len(categories[cat_name])} elementi')

    return categories


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit('uso: python extract_poi_offline.py <percorso.gpkg>')
    gpkg_path = sys.argv[1]

    categories = fetch(gpkg_path)
    payload = {
        'generated_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'source': f'OpenStreetMap contributors, estratto locale {Path(gpkg_path).name} (ODbL)',
        'bbox': list(CONFIG_BBOX),
        'categories': categories,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print('scritto', OUT)


if __name__ == '__main__':
    main()
