"""Repair Tô Ký intersection discovery using local Geofabrik PBF.
No network; does not automatically select corridor START/END.
Install: pip install osmium pandas
"""
from pathlib import Path
from collections import defaultdict
import math, json, unicodedata, re
import pandas as pd
import osmium

ROOT=Path(__file__).resolve().parent
RAW=ROOT/'Data'/'Raw'; OUT=ROOT/'Data'/'Processed'
PBF=RAW/'vietnam-latest.osm.pbf'
DIAG=OUT/'Corridor_V8_To_Ky_OSM_Name_Diagnostic.csv'
# V8 may be available in same project; otherwise infer from main ways in live PBF first
DRIVABLE={'primary','secondary','tertiary','unclassified','residential','trunk','primary_link','trunk_link','secondary_link','tertiary_link','service','living_street'}
def norm(x):
    x=unicodedata.normalize('NFD',str(x or '').casefold().replace('đ','d'))
    x=''.join(c for c in x if unicodedata.category(c)!='Mn')
    return re.sub(r'\s+',' ',re.sub('[^a-z0-9]+',' ',x)).strip()
def target(name):
    x=norm(name)
    return x in ('to ky','duong to ky')  # exact main road; exclude hẻm and suffixes

def hav(a,b,c,d):
    p1,p2=math.radians(a),math.radians(c)
    q=math.sin((p2-p1)/2)**2+math.cos(p1)*math.cos(p2)*math.sin(math.radians(d-b)/2)**2
    return 12742*math.asin(min(1,math.sqrt(q)))

class Extract(osmium.SimpleHandler):
    def __init__(self):
        super().__init__(); self.main_nodes={};self.other=defaultdict(set);self.matched_ways=0;self.cross_ways=0
    def way(self,w):
        if w.tags.get('highway') not in DRIVABLE: return
        name=w.tags.get('name','')
        if not name: return
        if target(name):
            self.matched_ways+=1
            for n in w.nodes:
                if n.location.valid(): self.main_nodes[n.ref]=(n.lat,n.lon)
        else:
            # To limit memory, only retain connecting roads at main road nodes already identified.
            # This works because main ways are discovered in a first pass before this pass.
            for n in w.nodes:
                if n.ref in self.main_nodes:self.other[n.ref].add(name);self.cross_ways+=1
class MainPass(osmium.SimpleHandler):
    def __init__(self):
        super().__init__();self.nodes={};self.ways=0
    def way(self,w):
        if w.tags.get('highway') in DRIVABLE and target(w.tags.get('name','')):
            self.ways+=1
            for n in w.nodes:
                if n.location.valid(): self.nodes[n.ref]=(n.lat,n.lon)
class CrossPass(osmium.SimpleHandler):
    def __init__(self,main_nodes):
        super().__init__(); self.main_nodes=main_nodes;self.cross=defaultdict(set)
    def way(self,w):
        if w.tags.get('highway') not in DRIVABLE:return
        name=w.tags.get('name','')
        if not name or target(name):return
        for n in w.nodes:
            if n.ref in self.main_nodes:self.cross[n.ref].add(name)

def main():
    if not PBF.exists():raise SystemExit(f'Missing input PBF: {PBF}')
    OUT.mkdir(parents=True,exist_ok=True)
    print('Pass 1/2: finding exact Tô Ký/Đường Tô Ký ways...')
    a=MainPass();a.apply_file(str(PBF),locations=True)
    print(f'Main road ways: {a.ways}; nodes: {len(a.nodes)}')
    if not a.nodes:raise SystemExit('No main road ways found; check PBF source.')
    print('Pass 2/2: finding named connecting ways at shared OSM nodes...')
    b=CrossPass(a.nodes);b.apply_file(str(PBF),locations=False)
    rows=[]
    for node, names in b.cross.items():
        lat,lon=a.nodes[node]
        for name in sorted(names):
            rows.append({'corridor_name':'Tô Ký','district_old':'Quận 12','osmid':node,'latitude':lat,'longitude':lon,'matched_names':'Tô Ký | Đường Tô Ký','crossing_names':name,'source':'Geofabrik Vietnam OSM PBF','method':'shared_osm_node_exact_main_road_name','review_status':'PROVISIONAL_SCOPE_CHECK','endpoint_role':'NOT_SELECTED'})
    rows.sort(key=lambda r:(r['latitude'],r['longitude'],r['crossing_names']))
    # Collapse nearby duplicate nodes only when crossing street name is identical.
    dedup=[]
    for r in rows:
        if any(norm(r['crossing_names'])==norm(q['crossing_names']) and hav(r['latitude'],r['longitude'],q['latitude'],q['longitude']) < 0.045 for q in dedup):continue
        dedup.append(r)
    cols=['corridor_name','district_old','osmid','latitude','longitude','matched_names','crossing_names','source','method','review_status','endpoint_role']
    pd.DataFrame(dedup,columns=cols).to_csv(OUT/'Corridor_V9_To_Ky_Intersection_Candidates.csv',index=False,encoding='utf-8-sig')
    summ={'main_road_ways':a.ways,'main_road_nodes':len(a.nodes),'raw_shared_node_crossings':len(rows),'candidate_rows_after_45m_same_name_dedup':len(dedup),'auto_selected_endpoints':0,'caveat':'No administrative boundary check; review each candidate before adding to V7 or selecting endpoints'}
    (OUT/'Corridor_V9_To_Ky_QA.json').write_text(json.dumps(summ,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summ,ensure_ascii=False,indent=2))
    print('Output:',OUT)
if __name__=='__main__':main()
