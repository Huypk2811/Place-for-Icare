"""Get provisional corridor street centerlines from OpenStreetMap (OSMnx).

Run: python build_corridor_osm_geometry.py
Reads: Data/Raw/iCare_8_Corridor_Segments_DRAFT.csv
Writes: Data/Processed/Corridor_OSM_Roads_REVIEW.geojson, Corridor_OSM_QA.csv,
        Corridor_OSM_Summary.csv

This is road centerline RESEARCH, not confirmed road frontage, actual travel distance,
traffic volume, or site suitability. This script NEVER silently routes on other roads.
"""
import csv, json, math, unicodedata
from collections import defaultdict
from pathlib import Path

try:
    import osmnx as ox
    import networkx as nx
    from shapely.geometry import box
except ImportError as exc:
    raise SystemExit('Missing GIS library; run: python -m pip install osmnx networkx shapely') from exc

ROOT = Path(__file__).resolve().parent
RAW = ROOT / 'Data' / 'Raw'
OUT = ROOT / 'Data' / 'Processed'
SOURCE = RAW / 'iCare_8_Corridor_Segments_DRAFT.csv'
OUT.mkdir(parents=True, exist_ok=True)
if not SOURCE.exists():
    raise SystemExit(f'Missing file: {SOURCE}')

def read_csv(path):
    with path.open(encoding='utf-8-sig', newline='') as fp: return list(csv.DictReader(fp))

def write_csv(path, records, fields):
    with path.open('w', encoding='utf-8-sig', newline='') as fp:
        w=csv.DictWriter(fp,fields); w.writeheader(); w.writerows(records)

def norm(v):
    if not v: return ''
    s=unicodedata.normalize('NFD',str(v).lower().replace('đ','d'))
    return ' '.join(''.join(c for c in s if unicodedata.category(c)!='Mn' and (c.isalnum() or c.isspace())).split())

def road_names(data):
    names=data.get('name',[])
    if isinstance(names,str): names=[names]
    if not isinstance(names,(list,tuple,set)): names=[]
    return [norm(n) for n in names if n]

def hmeters(lat1, lon1, lat2, lon2):
    r=6371008.8; p1,p2=map(math.radians,(lat1,lat2)); dp=p2-p1;dl=math.radians(lon2-lon1)
    return 2*r*math.asin(min(1,math.sqrt(math.sin(dp/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2)))

def nearest_node(G, lat, lon):
    return min(G.nodes, key=lambda n:hmeters(lat,lon,G.nodes[n]['y'],G.nodes[n]['x']))

rows=read_csv(SOURCE)
if len(rows)!=8: print(f'NOTE: found {len(rows)} segments, not 8')
# Keep a cache per district to avoid redundant Overpass calls.
districts=defaultdict(list)
for idx,row in enumerate(rows,1):
    district=row['district_old']
    districts[district].append((idx,row))

features=[]; qa=[]; summary=[]
for district,items in districts.items():
    lats=[float(r[k]) for _,r in items for k in ('start_lat','end_lat')]
    lons=[float(r[k]) for _,r in items for k in ('start_lon','end_lon')]
    pad=.018 # approx 2 km geographical buffer around known endpoints
    poly=box(min(lons)-pad,min(lats)-pad,max(lons)+pad,max(lats)+pad)
    print(f'Downloading OSM road network for {district} ...',flush=True)
    try:
        G=ox.graph_from_polygon(poly,network_type='drive',simplify=False,retain_all=True)
    except Exception as exc:
        print(f'OSM request failed for {district}: {exc}',flush=True)
        for i,r in items:
            cid=f"{'Q7' if district=='Quận 7' else 'GV'}-{i:02d}"
            qa.append({'corridor_id':cid,'status':'OSM_DOWNLOAD_FAILED','details':str(exc)[:240]})
            summary.append({'corridor_id':cid,'road_name':r['corridor_name'],'status':'OSM_DOWNLOAD_FAILED','road_length_km':'','start_snap_m':'','end_snap_m':''})
        continue
    for i,r in items:
        cid=f"{'Q7' if district=='Quận 7' else 'GV'}-{i:02d}"
        target=norm(r['corridor_name'])
        street=nx.Graph()
        # Only edges with road name EXACTLY matching corridor, not arbitrary nearby highways.
        for u,v,key,data in G.edges(keys=True,data=True):
            if target not in road_names(data): continue
            if u==v: continue
            length=float(data.get('length') or hmeters(G.nodes[u]['y'],G.nodes[u]['x'],G.nodes[v]['y'],G.nodes[v]['x']))
            if not street.has_edge(u,v) or length<street.edges[u,v]['weight']:
                street.add_edge(u,v,weight=length)
        if street.number_of_edges()==0:
            qa.append({'corridor_id':cid,'status':'ROAD_NAME_NOT_FOUND','details':f'No OSM drivable edges with name: {r["corridor_name"]}'})
            summary.append({'corridor_id':cid,'road_name':r['corridor_name'],'status':'ROAD_NAME_NOT_FOUND','road_length_km':'','start_snap_m':'','end_snap_m':''})
            continue
        a=(float(r['start_lat']),float(r['start_lon'])); b=(float(r['end_lat']),float(r['end_lon']))
        s=nearest_node(street,a[0],a[1])
        t=nearest_node(street,b[0],b[1])
        ds=hmeters(a[0],a[1],G.nodes[s]['y'],G.nodes[s]['x'])
        dt=hmeters(b[0],b[1],G.nodes[t]['y'],G.nodes[t]['x'])
        if s==t:
            status='SAME_SNAP_NODE'; path=[]
        else:
            try:
                path=nx.shortest_path(street,s,t,weight='weight')
                status='REVIEW_REQUIRED'
            except nx.NetworkXNoPath:
                status='DISCONNECTED_NAMED_ROAD';path=[]
        if not path:
            qa.append({'corridor_id':cid,'status':status,'details':f'snap start={ds:.0f}m, end={dt:.0f}m; no matching named-road path'})
            summary.append({'corridor_id':cid,'road_name':r['corridor_name'],'status':status,'road_length_km':'','start_snap_m':round(ds),'end_snap_m':round(dt)})
            continue
        coords=[[G.nodes[n]['x'],G.nodes[n]['y']] for n in path]
        length_m=nx.path_weight(street,path,'weight')
        chord=hmeters(*a,*b)
        detour=(length_m/chord if chord else math.inf)
        flags=[]
        if ds>120 or dt>120: flags.append('ENDPOINT_SNAP_OVER_120M')
        if detour>2:flags.append('DETOUR_OVER_2X')
        if 'UNCONFIRMED' in r.get('status','').upper():flags.append('SOURCE_INTERSECTION_UNCONFIRMED')
        if len(coords)<2: flags.append('INSUFFICIENT_NODES')
        for flag in flags: qa.append({'corridor_id':cid,'status':flag,'details':f'snap_start={ds:.0f}m, snap_end={dt:.0f}m; detour={detour:.2f}'})
        features.append({'type':'Feature','properties':{'corridor_id':cid,'district_old':district,'corridor_name':r['corridor_name'],'geometry_source':'OSMnx_OpenStreetMap','geometry_status':'PROVISIONAL_NEEDS_VISUAL_QA','start_snap_m':round(ds),'end_snap_m':round(dt),'route_length_km':round(length_m/1000,3),'qa_flags':';'.join(flags)},'geometry':{'type':'LineString','coordinates':coords}})
        summary.append({'corridor_id':cid,'road_name':r['corridor_name'],'status':'REVIEW_REQUIRED' if flags else 'PROVISIONAL_REVIEW','road_length_km':round(length_m/1000,3),'start_snap_m':round(ds),'end_snap_m':round(dt)})
        print(f'{cid} {r["corridor_name"]}: {length_m/1000:.2f}km, snaps {ds:.0f}/{dt:.0f}m, flags={flags}',flush=True)

(OUT/'Corridor_OSM_Roads_REVIEW.geojson').write_text(json.dumps({'type':'FeatureCollection','features':features},ensure_ascii=False,indent=2),encoding='utf-8')
write_csv(OUT/'Corridor_OSM_QA.csv',qa,['corridor_id','status','details'])
write_csv(OUT/'Corridor_OSM_Summary.csv',summary,['corridor_id','road_name','status','road_length_km','start_snap_m','end_snap_m'])
print(json.dumps({'segments_requested':len(rows),'road_geometries_provisional':len(features),'qa_flags':len(qa),'output':str(OUT),'note':'Must visually verify OSM polylines before treating as validated'},ensure_ascii=False,indent=2))
