"""Diagnose the missing Tô Ký corridor using local OSM PBF; no network calls.
Outputs are diagnostic evidence only, NEVER automatically selected endpoints.
"""
from pathlib import Path
import csv, json, unicodedata
try:
    import osmium
except ImportError as exc:
    raise SystemExit('Missing dependency: python -m pip install osmium') from exc

ROOT = Path(__file__).resolve().parent
PBF_DIR = ROOT / 'Data' / 'Raw'
PBF = PBF_DIR / 'vietnam-latest.osm.pbf'
OUT = ROOT / 'Data' / 'Processed'
OUT.mkdir(parents=True, exist_ok=True)
if not PBF.exists():
    raise SystemExit(f'Missing PBF: {PBF}')

def normalize(s):
    s = unicodedata.normalize('NFD', str(s or '').casefold())
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    return ' '.join(s.replace('đ', 'd').split())

FIELDS = ('name', 'alt_name', 'official_name', 'old_name', 'name:vi', 'short_name', 'loc_name')
class Scan(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.results=[]
        self.total_ways=0
        self.named_ways=0
    def way(self,w):
        self.total_ways+=1
        if 'highway' not in w.tags:
            return
        tags = {k: w.tags.get(k, '') for k in FIELDS}
        matched = {k:v for k,v in tags.items() if 'to ky' in normalize(v)}
        if not matched:
            return
        self.named_ways+=1
        coords=[]
        for n in w.nodes:
            try:
                if n.location.valid():
                    coords.append((n.location.lat, n.location.lon))
            except (ValueError, RuntimeError):
                pass
        self.results.append({
            'osmid':w.id,'highway':w.tags.get('highway',''),
            'name':tags['name'],'matched_tag_values':json.dumps(matched,ensure_ascii=False),
            'node_count':len(coords),
            'centroid_lat':round(sum(x for x,_ in coords)/len(coords),7) if coords else '',
            'centroid_lon':round(sum(y for _,y in coords)/len(coords),7) if coords else '',
            'first_lat':round(coords[0][0],7) if coords else '',
            'first_lon':round(coords[0][1],7) if coords else '',
            'last_lat':round(coords[-1][0],7) if coords else '',
            'last_lon':round(coords[-1][1],7) if coords else '',
            'in_original_bbox': bool(coords and any(10.812708<=lat<=10.881833 and 106.597215<=lon<=106.641567 for lat,lon in coords)),
        })

print('Scanning local PBF for Tô Ký road names; this may take a while...')
h=Scan()
h.apply_file(str(PBF),locations=True)
out_csv=OUT/'Corridor_V8_To_Ky_OSM_Name_Diagnostic.csv'
with out_csv.open('w',encoding='utf-8-sig',newline='') as f:
    fields=['osmid','highway','name','matched_tag_values','node_count','centroid_lat','centroid_lon','first_lat','first_lon','last_lat','last_lon','in_original_bbox']
    wr=csv.DictWriter(f,fieldnames=fields);wr.writeheader();wr.writerows(h.results)
summary={
 'source_pbf':str(PBF),'total_ways_scanned':h.total_ways,
 'named_road_ways_matching_to_ky':h.named_ways,
 'matching_ways_intersecting_original_bbox':sum(x['in_original_bbox'] for x in h.results),
 'auto_selected_endpoints':0,
 'note':'Name/alias diagnostic only. A matching way is not an intersection or a selected corridor endpoint.'
}
with (OUT/'Corridor_V8_To_Ky_Diagnostic_Summary.json').open('w',encoding='utf-8') as f:
    json.dump(summary,f,indent=2,ensure_ascii=False)
print(json.dumps(summary,indent=2,ensure_ascii=False))
print('Outputs:',out_csv.name,'and Corridor_V8_To_Ky_Diagnostic_Summary.json')
