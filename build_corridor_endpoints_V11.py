"""iCare V11: evidence-traceable corridor endpoint review, not site ranking.
Run from project root: python build_corridor_endpoints_V11.py
Inputs: Data/Processed/Corridor_V10_Intersection_Review.csv,
        Data/Raw/Data_input_TOP5_FRAMEWORK_V3.xlsx (fallback to root).
Outputs: 4 CSV + summary JSON in Data/Processed.
"""
from pathlib import Path
from collections import defaultdict,Counter
import csv,json,math,unicodedata
from openpyxl import load_workbook

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'Data'/'Processed'; RAW=ROOT/'Data'/'Raw'
CORRIDORS={'Quận 12':['Đỗ Mười','Lê Văn Khương','Nguyễn Ảnh Thủ','Tô Ký','Hà Huy Giáp'],
 'Bình Tân':['Kinh Dương Vương','QL1 / Lê Đức Anh','Tên Lửa','Tân Kỳ Tân Quý','Võ Trần Chí'],
 'Bình Thạnh':['Xô Viết Nghệ Tĩnh','Quốc lộ 13','Đinh Bộ Lĩnh','Nguyễn Xí','Nơ Trang Long']}
MIN_SEPARATION_KM=0.65 # technical review-window heuristic, NOT business criterion
MAX_SEPARATION_KM=3.50

def norm(x):
 s=unicodedata.normalize('NFD',str(x or '').lower().replace('đ','d'))
 return ' '.join(''.join(c for c in s if unicodedata.category(c)!='Mn' and (c.isalnum() or c.isspace())).split())
def dist(a,b):
 p1,p2=math.radians(a['lat']),math.radians(b['lat'])
 dl=math.radians(b['lon']-a['lon']);dp=p2-p1
 t=math.sin(dp/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
 return 12742*math.asin(min(1,math.sqrt(t)))
def readcsv(p):
 with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def savecsv(path,rows,fields):
 with path.open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(rows)
def sheet(wb,name):
 if name not in wb.sheetnames:return []
 it=wb[name].values;h=next(it)
 return [dict(zip(h,r)) for r in it if any(v is not None for v in r)]
def safe(v):return '' if v is None else str(v)

def main():
 OUT.mkdir(parents=True,exist_ok=True)
 ip=OUT/'Corridor_V10_Intersection_Review.csv'
 if not ip.exists():raise SystemExit(f'Missing {ip}: run V10 first')
 wp=next((p for p in [RAW/'Data_input_TOP5_FRAMEWORK_V3.xlsx',ROOT/'Data_input_TOP5_FRAMEWORK_V3.xlsx'] if p.exists()),None)
 if wp is None:raise SystemExit('Missing Data_input_TOP5_FRAMEWORK_V3.xlsx in Data/Raw or root')
 wb=load_workbook(wp,read_only=True,data_only=True)
 studies=sheet(wb,'15_Top3_Corridor_Research'); traffic=sheet(wb,'16_Top3_Corridor_Evidence')
 anchors=sheet(wb,'18_Corridor_Context_Anchors');rents=sheet(wb,'22_Corridor_Rent_Summary')
 src=readcsv(ip); grouped=defaultdict(list);rejections=[]
 for r in src:
  key=(norm(r.get('district_old')),norm(r.get('corridor_name')))
  try:
   lat=float(r['latitude']);lon=float(r['longitude'])
   if not (8<lat<12 and 105<lon<108):raise ValueError('outside HCMC broad sanity bounds')
  except (ValueError,KeyError) as e:
   rejections.append({'candidate_id':r.get('candidate_id',''),'reason':f'BAD_COORD: {e}'});continue
  d={**r,'lat':lat,'lon':lon}
  grouped[key].append(d)
 evidence=[];points=[];pairs=[];summary=[]
 for district,roads in CORRIDORS.items():
  for road in roads:
   key=(norm(district),norm(road));rr=grouped.get(key,[])
   # same source OSM ID may occur multiple times; preserve input rows and flag not independently verified
   u=[];ids=set()
   for p in rr:
    identity=(p.get('source_osmid') or p.get('osmid') or p.get('intersection_id'),round(p['lat'],6),round(p['lon'],6))
    if identity in ids:continue
    ids.add(identity);u.append(p)
   rr=u
   rec=next((r for r in studies if norm(r.get('district'))==key[0] and norm(r.get('corridor'))==key[1]),{})
   e=[r for r in traffic if norm(r.get('district'))==key[0] and norm(r.get('corridor'))==key[1]]
   a=[r for r in anchors if norm(r.get('district'))==key[0] and norm(r.get('corridor'))==key[1]]
   rent=next((r for r in rents if norm(r.get('district'))==key[0] and norm(r.get('corridor'))==key[1]),{})
   evidence.append({'district_old':district,'corridor_name':road,'network_role':safe(rec.get('network_role')),
      'historic_research_reason':safe(rec.get('why_selected_for_deep_dive')),
      'traffic_source_urls':' | '.join(sorted({safe(x.get('source_url')) for x in e if x.get('source_url')})),
      'traffic_source_dates':' | '.join(sorted({safe(x.get('evidence_date')) for x in e if x.get('evidence_date')})),
      'traffic_evidence_categories':' | '.join(sorted({safe(x.get('evidence_category')) for x in e if x.get('evidence_category')})),
      'anchor_names':' | '.join(sorted({safe(x.get('anchor_or_signal')) for x in a if x.get('anchor_or_signal')})),
      'anchor_urls':' | '.join(sorted({safe(x.get('source_url')) for x in a if x.get('source_url')})),
      'clean_rent_n':safe(rent.get('clean_current_usable_n')),'rent_median_million':safe(rent.get('median_rent_million_month')),
      'evidence_scope':'WHOLE_CORRIDOR_NOT_GEOLOCATED_TO_SEGMENT',
      'traffic_caution':'Sources are evidence breadth/context, not traffic volume',
      'rent_caution':'Historic median is corridor-level only; do not attach to proposed segment without listing address review'})
   for p in rr:
    points.append({'district_old':district,'corridor_name':road,'intersection_id':safe(p.get('intersection_id')),
     'crossing_names':safe(p.get('crossing_names')),'latitude':p['lat'],'longitude':p['lon'],
     'source_osmid':safe(p.get('source_osmid') or p.get('osmid')),'source_phase':safe(p.get('source_phase')),
     'status':'OSM_INTERSECTION_CANDIDATE_UNVERIFIED'})
   # Propose up to 2 alternative review windows using *only spatial separation*.
   # Never claim road-following route or business-fit; end point selection remains unresolved.
   named=[r for r in rr if r.get('crossing_names') and 'hẻm' not in norm(r['crossing_names']) and 'hem' not in norm(r['crossing_names'])]
   alternatives=[]
   for i,p in enumerate(named):
    for q in named[i+1:]:
     d=dist(p,q)
     if MIN_SEPARATION_KM<=d<=MAX_SEPARATION_KM:
      alternatives.append((d,p,q))
   # Spread out distances to avoid choosing only the longest segment; index by target spans.
   chosen=[];seen=set()
   for target in (1.4,2.5):
    for d,p,q in sorted(alternatives,key=lambda x:abs(x[0]-target)):
     ids=tuple(sorted((str(p.get('intersection_id')),str(q.get('intersection_id')))))
     if ids not in seen:
      chosen.append((d,p,q));seen.add(ids);break
   for ix,(d,p,q) in enumerate(chosen,1):
    pairs.append({'district_old':district,'corridor_name':road,'review_option':f'OPTION_{ix}',
     'start_intersection_id':safe(p.get('intersection_id')),'start_cross_street':safe(p.get('crossing_names')),
     'start_lat':p['lat'],'start_lon':p['lon'],'end_intersection_id':safe(q.get('intersection_id')),
     'end_cross_street':safe(q.get('crossing_names')),'end_lat':q['lat'],'end_lon':q['lon'],
     'straight_distance_km':round(d,3),'endpoint_method':'GEOMETRY_ONLY_CANDIDATE_PAIR',
     'research_trace':'See Corridor_V11_Evidence_Audit.csv; evidence is NOT mapped to this segment',
     'qa_status':'NEED_ROUTE_GEOMETRY_AND_BUSINESS_ANCHOR_VALIDATION',
     'decision':'NOT_SELECTED','selection_warning':'Pair is heuristic only, not a recommended or validated business segment'})
   summary.append({'district_old':district,'corridor_name':road,'intersection_candidates':len(rr),
      'named_candidates':len(named),'review_pairs':len(chosen),
      'status':'REVIEW_PAIRS_CREATED' if chosen else 'INSUFFICIENT_CANDIDATE_PAIRS',
      'next_step':'Geolocate anchor/rent listing and select supported segment; validate OSM route and boundary'})
 savecsv(OUT/'Corridor_V11_Endpoint_Review_Options.csv',pairs,list(pairs[0]) if pairs else ['district_old','corridor_name','review_option'])
 savecsv(OUT/'Corridor_V11_Evidence_Audit.csv',evidence,list(evidence[0]))
 savecsv(OUT/'Corridor_V11_Candidate_Point_Index.csv',points,list(points[0]))
 savecsv(OUT/'Corridor_V11_Corridor_Status.csv',summary,list(summary[0]))
 result={'corridors':len(summary),'intersections_indexed':len(points),'review_pairs':len(pairs),
 'corridors_with_review_pairs':sum(s['review_pairs']>0 for s in summary),
 'auto_selected_endpoints':0,'input_workbook':wp.name,
 'limitations':['Review pairs use straight-line distance as a technical heuristic, not road length',
 'Historic evidence URLs/anchors apply at corridor level, not verified to paired endpoints',
 'No attractiveness score or site recommendation','OSM candidates not independently validated']}
 (OUT/'Corridor_V11_Run_Summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(result,ensure_ascii=False,indent=2));print('Outputs:',OUT)
if __name__=='__main__':main()
