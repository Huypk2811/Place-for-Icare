"""iCare corridor intersection candidates from local Geofabrik Vietnam OSM PBF.

Reads 15 historic candidate corridors from V3 inventory, three historic district GPS
clusters from the Top5 workbook. Exports INTERSECTION CANDIDATES only (not START/END).
No Overpass requests. Requires: pip install osmium pandas openpyxl.
"""
from pathlib import Path
import csv, json, math, re, unicodedata
from collections import defaultdict

import pandas as pd
from openpyxl import load_workbook
try:
    import osmium
except ImportError as exc:
    raise SystemExit('Missing pyosmium. Install: python -m pip install osmium') from exc

ROOT = Path(__file__).resolve().parent
RAW, OUT = ROOT/'Data'/'Raw', ROOT/'Data'/'Processed'
PBF = RAW/'vietnam-latest.osm.pbf'
INVENTORY = OUT/'Corridor_V3_Inventory_31.csv'
WORKBOOK = RAW/'Data_input_TOP5_FRAMEWORK_V3.xlsx'
TARGETS = ('Quận 12','Bình Tân','Bình Thạnh')
PAD_KM = 1.8
MAX_CANDIDATES_PER_CORRIDOR = 80
DRIVE_HIGHWAYS = {'motorway','trunk','primary','secondary','tertiary','unclassified','residential','living_street','service','motorway_link','trunk_link','primary_link','secondary_link','tertiary_link'}


def normalize(s):
    s = unicodedata.normalize('NFD',str(s or '').lower().replace('đ','d'))
    s = ''.join(c for c in s if unicodedata.category(c)!='Mn')
    return re.sub(r'[^a-z0-9]+',' ',s).strip()


def km(a,b,c,d):
    p1,p2=math.radians(a),math.radians(c)
    x=math.sin((p2-p1)/2)**2+math.cos(p1)*math.cos(p2)*math.sin(math.radians(d-b)/2)**2
    return 12742*math.asin(min(1,math.sqrt(x)))


def gps_bounds():
    w=load_workbook(WORKBOOK,read_only=True,data_only=True)
    ws=w['04_Market_Locations']; rows=ws.values; header=next(rows)
    idx={v:i for i,v in enumerate(header)}
    by=defaultdict(list)
    for r in rows:
        district=str(r[idx['district_old']] or '').strip()
        if district not in TARGETS: continue
        try:
            lat=float(r[idx['latitude']]); lon=float(r[idx['longitude']])
            if not (10<lat<12 and 106<lon<108):continue
            by[district].append((lat,lon))
        except (TypeError,ValueError):pass
    bounds={}
    for dist in TARGETS:
        pts=by[dist]
        if not pts:raise ValueError(f'No GPS for {dist} in workbook')
        latmin=min(p[0] for p in pts);latmax=max(p[0] for p in pts)
        lonmin=min(p[1] for p in pts);lonmax=max(p[1] for p in pts)
        latpad=PAD_KM/111.2;lonpad=PAD_KM/(111.2*math.cos(math.radians((latmin+latmax)/2)))
        bounds[dist]=(lonmin-lonpad,latmin-latpad,lonmax+lonpad,latmax+latpad)
    return bounds,by


def within(lat,lon,b):
    return b[0]<=lon<=b[2] and b[1]<=lat<=b[3]


class RoadHandler(osmium.SimpleHandler):
    def __init__(self,bounds):
        super().__init__();self.bounds=bounds
        self.nodes=defaultdict(lambda:{'coord':None,'names':set()})
        self.edge_count=defaultdict(int)
    def way(self,w):
        if w.tags.get('highway') not in DRIVE_HIGHWAYS:return
        name=w.tags.get('name','')
        if not name:return
        norm=normalize(name)
        try:
            coords=[(n.ref,n.lat,n.lon) for n in w.nodes if n.location.valid()]
        except (ValueError,RuntimeError):return
        if not coords:return
        for district,bbox in self.bounds.items():
            if not any(within(lat,lon,bbox) for _,lat,lon in coords):continue
            self.edge_count[district]+=1
            for ident,lat,lon in coords:
                if within(lat,lon,bbox):
                    node=self.nodes[(district,ident)]
                    node['coord']=(lat,lon)
                    node['names'].add((norm,name))


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    for p in (PBF,INVENTORY,WORKBOOK):
        if not p.exists():raise SystemExit(f'Missing input: {p}')
    data=pd.read_csv(INVENTORY).fillna('')
    old=data[data['district_old'].isin(TARGETS)].copy()
    if len(old)!=15:raise ValueError(f'Expected 15 old corridors; got {len(old)}')
    bounds,gps=gps_bounds()
    print('Reading local PBF (no web calls):',PBF)
    handler=RoadHandler(bounds)
    handler.apply_file(str(PBF),locations=True)
    print('Road ways found in bounds:',dict(handler.edge_count))
    rows=[]; qa=[]
    # Compare each candidate to all nodes in the corresponding historic district bounding box.
    for _,r in old.iterrows():
        cid,district,road=r['candidate_id'],r['district_old'],str(r['corridor_name'])
        aliases=[road]
        if '/' in road:aliases += [p.strip() for p in road.split('/')]
        if normalize(road)=='do muoi':aliases+=['Quốc lộ 1','Quốc lộ 1A']
        alias_norm={normalize(a) for a in aliases}
        found=[]
        for (dist,nodeid),entry in handler.nodes.items():
            if dist!=district or entry['coord'] is None:continue
            names=entry['names']
            matched=[nm for nm,original in names if nm in alias_norm]
            cross=sorted(set(original for nm,original in names if nm not in alias_norm))
            if matched and cross:
                lat,lon=entry['coord']
                near=min((km(lat,lon,p[0],p[1]) for p in gps[district]),default=999)
                found.append((near,lat,lon,nodeid,sorted(set(original for nm,original in names if nm in alias_norm)),cross))
        found.sort(key=lambda v:v[0])
        unique=[]
        for point in found:
            if any(km(point[1],point[2],q[1],q[2])<0.045 and point[5]==q[5] for q in unique):continue
            unique.append(point)
        for j,(near,lat,lon,nodeid,matched,cross) in enumerate(unique[:MAX_CANDIDATES_PER_CORRIDOR],1):
            rows.append(dict(intersection_id=f'{cid}-I{j:03}',candidate_id=cid,district_old=district,corridor_name=road,
                             latitude=round(lat,8),longitude=round(lon,8),osmid=nodeid,matched_names=' | '.join(matched),
                             crossing_names=' | '.join(cross),nearest_observed_gps_km=round(near,3),
                             source='Geofabrik Vietnam OSM PBF',method='shared_osm_node_named_drive_ways',
                             review_status='PROVISIONAL_CHECK_ON_MAP',alias_match_review=int(normalize(road)=='do muoi' or '/' in road)))
        qa.append(dict(candidate_id=cid,district_old=district,corridor_name=road,
                       status='CANDIDATES_FOUND_REVIEW' if unique else 'NO_NAMED_INTERSECTIONS_IN_GPS_BBOX',
                       candidates_found=len(unique),candidates_exported=min(len(unique),MAX_CANDIDATES_PER_CORRIDOR),
                       note='Candidate discovery only; observed competitor BBOX is not full district boundary; no endpoint selection.'))
    paths=[OUT/'Corridor_V4_Intersection_Candidates.csv',OUT/'Corridor_V4_Endpoint_QA.csv']
    pd.DataFrame(rows,columns=['intersection_id','candidate_id','district_old','corridor_name','latitude','longitude','osmid','matched_names','crossing_names','nearest_observed_gps_km','source','method','review_status','alias_match_review']).to_csv(paths[0],index=False,encoding='utf-8-sig')
    pd.DataFrame(qa).to_csv(paths[1],index=False,encoding='utf-8-sig')
    summary={'old_corridors_requested':len(old),'intersection_candidates_exported':len(rows),'corridors_with_candidates':sum(q['candidates_found']>0 for q in qa),'source':str(PBF),'bbox_method':'observed competitor GPS + 1.8km padding; incomplete geographic coverage','auto_selected_endpoints':0,'network_requests':0}
    (OUT/'Corridor_V4_Run_Summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    print('Outputs:',OUT)

if __name__=='__main__':main()
