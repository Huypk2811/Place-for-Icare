"""iCare corridor spatial baseline (stdlib only).

Run from project root: python build_corridor_spatial_baseline.py
Reads three evidence CSVs in Data/Raw, writes Data/Processed.
Distances to START-END chords are screening proxies, NOT real road geometry.
Optionally supply verified corridor GeoJSON LineStrings via --roads to get road geometry.
"""
import argparse, csv, json, math
from pathlib import Path
from collections import Counter

R=6371.0088

def load_rows(path):
    with open(path, encoding='utf-8-sig', newline='') as f: return list(csv.DictReader(f))
def write_rows(path, rows, keys):
    path.parent.mkdir(parents=True,exist_ok=True)
    with open(path,'w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=keys,extrasaction='ignore'); w.writeheader();w.writerows(rows)
def hav(a,b):
    la1,lo1=map(math.radians,a); la2,lo2=map(math.radians,b)
    dlat=la2-la1;dlon=lo2-lo1
    return 2*R*math.asin(min(1,math.sqrt(math.sin(dlat/2)**2+math.cos(la1)*math.cos(la2)*math.sin(dlon/2)**2)))
def xy(point, lat0):
    return (R*math.radians(point[1])*math.cos(math.radians(lat0)),R*math.radians(point[0]))
def to_segment_km(p,a,b):
    lat0=sum([p[0],a[0],b[0]])/3
    px,py=xy(p,lat0);ax,ay=xy(a,lat0);bx,by=xy(b,lat0)
    dx,dy=bx-ax,by-ay; den=dx*dx+dy*dy
    t=max(0,min(1,((px-ax)*dx+(py-ay)*dy)/den)) if den else 0
    return math.hypot(px-(ax+t*dx),py-(ay+t*dy)),t

def road_geometry(path):
    if not path: return {}
    data=json.loads(Path(path).read_text(encoding='utf-8-sig'))
    out={}
    for ft in data['features']:
        prop=ft.get('properties',{}); key=prop.get('corridor_id')
        geo=ft.get('geometry',{})
        if not key or geo.get('type')!='LineString': continue
        out[key]=[(float(lat),float(lon)) for lon,lat,*_ in geo['coordinates']]
    return out

def main():
    pa=argparse.ArgumentParser();pa.add_argument('--raw',type=Path,default=Path('Data/Raw'))
    pa.add_argument('--output',type=Path,default=Path('Data/Processed'))
    pa.add_argument('--roads',type=Path,default=None,help='optional verified centerline GeoJSON with corridor_id property')
    args=pa.parse_args()
    filenames=('iCare_12_Intersection_Points_DRAFT.csv','iCare_8_Corridor_Segments_DRAFT.csv','iCare_Q7_GoVap_12_GPS_Points_verified_update.csv')
    paths=[args.raw/x for x in filenames]
    for p in paths:
        if not p.exists(): raise FileNotFoundError(f'Missing {p}; copy supplied CSV to Data/Raw')
    pts,segs,places=[load_rows(p) for p in paths]
    by_id={p['point_id']:p for p in pts}
    roads=road_geometry(args.roads)
    issues=[]; corridor_rows=[]; matches=[]
    for i,s in enumerate(segs,1):
        cid=f"{'Q7' if s['district_old']=='Quận 7' else 'GV'}-{i:02d}"
        a=by_id[s['start_id']];b=by_id[s['end_id']]
        acoord=(float(a['latitude']),float(a['longitude']));bcoord=(float(b['latitude']),float(b['longitude']))
        raw_a=(float(s['start_lat']),float(s['start_lon']));raw_b=(float(s['end_lat']),float(s['end_lon']))
        if hav(acoord,raw_a)>0.001 or hav(bcoord,raw_b)>0.001:issues.append({'corridor_id':cid,'severity':'ERROR','issue':'Endpoint CSV coordinates differ from intersection master'})
        chord=hav(acoord,bcoord)
        if chord<0.2: issues.append({'corridor_id':cid,'severity':'REVIEW','issue':'Very short segment (<200m)'})
        geom=roads.get(cid)
        if geom and len(geom)<2: issues.append({'corridor_id':cid,'severity':'ERROR','issue':'Road geometry contains <2 points'});geom=None
        if geom:
            road_km=sum(hav(geom[j],geom[j+1]) for j in range(len(geom)-1))
            if min(hav(geom[0],acoord)+hav(geom[-1],bcoord),hav(geom[-1],acoord)+hav(geom[0],bcoord))>.1:
                issues.append({'corridor_id':cid,'severity':'REVIEW','issue':'Road geometry endpoints >100m total from supplied intersections'})
        else: road_km=None
        if a.get('validation_status')!='USER_COORDINATE_PROVIDED' or b.get('validation_status')!='USER_COORDINATE_PROVIDED':
            issues.append({'corridor_id':cid,'severity':'REVIEW','issue':'Endpoint geometry not independently verified'})
        corridor_rows.append({'corridor_id':cid,'district_old':s['district_old'],'corridor_name':s['corridor_name'],'start_id':s['start_id'],'end_id':s['end_id'],'chord_km':round(chord,3),'road_centerline_km':round(road_km,3) if road_km is not None else '', 'geometry_type':'VERIFIED_GEOJSON' if geom else 'START_END_CHORD_PROXY','geometry_status':'READY_FOR_MAP_MATCH_REVIEW' if geom else 'NEEDS_ROAD_CENTERLINE','validation_status':s['status'],'point_count':0,'nearby_anchors_250m':0,'nearby_competitors_250m':0,'method_note':'Distance-to-chord is not distance-to-road; no route, traffic or catchment inference' if not geom else 'Distance-to-supplied road centerline; verify provenance and projection'})
        for p in places:
            if p['research_area']!=s['district_old']:continue
            pc=(float(p['latitude']),float(p['longitude']))
            line=geom if geom else [acoord,bcoord]
            dd=[to_segment_km(pc,line[j],line[j+1])[0] for j in range(len(line)-1)]
            dist=min(dd)
            matches.append({'corridor_id':cid,'corridor_name':s['corridor_name'],'district_old':s['district_old'],'place_name_address':p['point_name_address'],'point_type':p['point_type'],'distance_to_geometry_m':round(dist*1000),'geometry_type':'VERIFIED_GEOJSON' if geom else 'START_END_CHORD_PROXY','within_250m_provisional':int(dist<=.25),'within_500m_provisional':int(dist<=.5),'coordinate_status':p['coordinate_status'],'note':'Proximity is spatial only; does NOT imply direct frontage, road access or demand'})
            corridor_rows[-1]['point_count']+=1
            if dist<=.25:
                k='nearby_competitors_250m' if p['point_type']=='competitor' else 'nearby_anchors_250m'
                corridor_rows[-1][k]+=1
    # Stop double-counting: overlapping segments can associate one point to multiple corridors.
    write_rows(args.output/'Corridor_Spatial_8_DRAFT.csv',corridor_rows,list(corridor_rows[0]))
    write_rows(args.output/'Corridor_Point_Proximity_DRAFT.csv',matches,list(matches[0]))
    write_rows(args.output/'Corridor_Geometry_QA.csv',issues,['corridor_id','severity','issue'])
    summary={'segments':len(corridor_rows),'intersections':len(pts),'places':len(places),'road_geometry_loaded':len(roads),'qa_findings':len(issues),'method':'WGS84 Haversine endpoint distances + local tangent-plane point-to-segment for descriptive proxy. No traffic volume or road travel distance.'}
    (args.output/'Corridor_Spatial_Run_Summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2));print('Output:',args.output.resolve())
if __name__=='__main__':main()
