"""iCare corridor registry V3 — 5 districts / 31 candidates.

Run: python build_corridor_pipeline_V3.py
Optional (Internet): python build_corridor_pipeline_V3.py --scan-osm

Read-only input: Data/Raw/Data_input_TOP5_FRAMEWORK_V3.xlsx (or project root / same workbook),
Data/Raw/iCare_8_Corridor_Segments_DRAFT.csv, Data/Processed/Corridor_OSM_Roads_REVIEW.geojson.
Outputs: Data/Processed/Corridor_V3_Inventory_31.csv,
 Corridor_V3_Endpoint_Research_Gaps.csv, Corridor_V3_Geometry_QA.csv,
 Corridor_V3_OSM_Name_Discovery.csv (with --scan-osm), Corridor_V3_Methodology.json.
Never guesses endpoints. No attractiveness score or traffic volume is inferred.
"""
import argparse, csv, json, math, unicodedata
from pathlib import Path
from collections import Counter
from openpyxl import load_workbook

ROOT=Path(__file__).resolve().parent; RAW=ROOT/'Data'/'Raw'; OUT=ROOT/'Data'/'Processed'
OLD={
'Quận 12':['Đỗ Mười','Lê Văn Khương','Nguyễn Ảnh Thủ','Tô Ký','Hà Huy Giáp'],
'Bình Tân':['Kinh Dương Vương','QL1 / Lê Đức Anh','Tên Lửa','Tân Kỳ Tân Quý','Võ Trần Chí'],
'Bình Thạnh':['Xô Viết Nghệ Tĩnh','Quốc lộ 13','Đinh Bộ Lĩnh','Nguyễn Xí','Nơ Trang Long']}
NEW={'Quận 7':['Nguyễn Thị Thập','Huỳnh Tấn Phát','Nguyễn Hữu Thọ','Nguyễn Văn Linh','Lâm Văn Bền','Nguyễn Lương Bằng','Trần Xuân Soạn','Đào Trí'],
'Gò Vấp':['Quang Trung','Phan Văn Trị','Nguyễn Văn Lượng','Nguyễn Oanh','Lê Đức Thọ','Thống Nhất','Phạm Văn Chiêu','Phan Huy Ích']}
ALL={**OLD,**NEW}

def norm(s):
 s=unicodedata.normalize('NFD',str(s or '').lower().replace('đ','d'))
 return ' '.join(''.join(c for c in s if unicodedata.category(c)!='Mn' and (c.isalnum() or c.isspace())).split())

def read_csv(p):
 with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))

def write_csv(p,rows,fields):
 with p.open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(rows)

def wb_sheet(wb,name):
 if not wb or name not in wb.sheetnames:return []
 vals=wb[name].values
 head=next(vals)
 return [dict(zip(head,row)) for row in vals if any(x is not None for x in row)]

def text(x):return '' if x is None else str(x)

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--scan-osm',action='store_true',help='OSM road-name reconnaissance only (no automatic START/END)')
 a=parser.parse_args();OUT.mkdir(parents=True,exist_ok=True)
 candidates=[RAW/'Data_input_TOP5_FRAMEWORK_V3.xlsx',ROOT/'Data_input_TOP5_FRAMEWORK_V3.xlsx']
 wbpath=next((p for p in candidates if p.exists()),None)
 if not wbpath:raise SystemExit('Missing Data_input_TOP5_FRAMEWORK_V3.xlsx in Data/Raw (or project root).')
 wb=load_workbook(wbpath,read_only=True,data_only=True)
 evidence={}
 for sheet in ['15_Top3_Corridor_Research','16_Top3_Corridor_Evidence','18_Corridor_Context_Anchors','22_Corridor_Rent_Summary']:
  evidence[sheet]=wb_sheet(wb,sheet)
 segpath=RAW/'iCare_8_Corridor_Segments_DRAFT.csv'
 if not segpath.exists():raise SystemExit(f'Missing {segpath}')
 segments={(r['district_old'],norm(r['corridor_name'])):r for r in read_csv(segpath)}
 geompath=OUT/'Corridor_OSM_Roads_REVIEW.geojson'
 geo={}
 if geompath.exists():
  with geompath.open(encoding='utf-8') as f: data=json.load(f)
  for feature in data.get('features',[]):
   p=feature.get('properties') or {};key=(p.get('district_old'),norm(p.get('corridor_name')))
   geo[key]=p
 rows=[];gaps=[];qa=[]
 for district,roads in ALL.items():
  for num,road in enumerate(roads,1):
   key=(district,norm(road));segment=segments.get(key);gp=geo.get(key)
   existing=(district in OLD)
   traffic=sum(1 for r in evidence['16_Top3_Corridor_Evidence'] if text(r.get('district'))==district and norm(r.get('corridor'))==norm(road))
   anchors=sum(1 for r in evidence['18_Corridor_Context_Anchors'] if text(r.get('district'))==district and norm(r.get('corridor'))==norm(road))
   rents=next((r for r in evidence['22_Corridor_Rent_Summary'] if text(r.get('district'))==district and norm(r.get('corridor'))==norm(road)),{})
   cid=('Q12' if district=='Quận 12' else 'BT' if district=='Bình Tân' else 'BTH' if district=='Bình Thạnh' else 'Q7' if district=='Quận 7' else 'GV')+'-'+f'{num:02d}'
   geom_status=gp.get('geometry_status','NO_OSM_GEOMETRY') if gp else 'NO_OSM_GEOMETRY'
   srcstatus=segment.get('status','') if segment else ''
   flags=gp.get('qa_flags','') if gp else ''
   r={'candidate_id':cid,'district_old':district,'corridor_name':road,'scope':'OLD_RESEARCH_15' if existing else 'NEW_CANDIDATES_16',
      'endpoint_status':'PROVIDED_DRAFT_REVIEW' if segment else 'NEED_CORRIDOR_SEGMENT_DEFINITION',
      'start_intersection':segment.get('start_intersection','') if segment else '',
      'start_lat':segment.get('start_lat','') if segment else '', 'start_lon':segment.get('start_lon','') if segment else '',
      'end_intersection':segment.get('end_intersection','') if segment else '',
      'end_lat':segment.get('end_lat','') if segment else '', 'end_lon':segment.get('end_lon','') if segment else '',
      'osm_geometry_status':geom_status,'osm_qa_flags':flags,'osm_length_km':gp.get('route_length_km','') if gp else '',
      'osm_unmatched_share':gp.get('unmatched_share','') if gp else '',
      'historic_traffic_evidence_rows':traffic,'historic_context_anchor_rows':anchors,
      'historic_clean_rent_n':text(rents.get('clean_current_usable_n')),'historic_rent_median_million':text(rents.get('median_rent_million_month')),
      'research_status':'HISTORIC_EVIDENCE_AVAILABLE' if existing else 'NEW_RESEARCH_PARTIAL',
      'scoring_eligible':'NO','reason':'Candidate registry only. Site accessibility, matched-road segmentation, 2026 source refresh, and full corridor evidence not yet validated.'}
   rows.append(r)
   if not segment:gaps.append({'candidate_id':cid,'district_old':district,'corridor_name':road,'gap':'START_END_NOT_DEFINED','recommended_action':'Review past corridor research, propose specific junctions from evidence; verify GPS later; do not select full named road automatically.'})
   if segment and not gp:gaps.append({'candidate_id':cid,'district_old':district,'corridor_name':road,'gap':'OSM_GEOMETRY_NOT_AVAILABLE','recommended_action':'Run existing V2 geometry tool / reconcile OSM names; QA required.'})
   if gp and (flags or geom_status not in ('PROVISIONAL_REVIEW','REVIEW_REQUIRED')):
    qa.append({'candidate_id':cid,'district_old':district,'corridor_name':road,'geometry_status':geom_status,'flags':flags,'action':'Review OSM geometry manually; exclude unmatched connector edges from business-point proximity; never equate provisional routing with actual frontage.'})
 expected=sum(map(len,ALL.values()))
 if len(rows)!=31 or expected!=31:raise AssertionError('Candidate inventory must have exactly 31 rows')
 fields=list(rows[0]); write_csv(OUT/'Corridor_V3_Inventory_31.csv',rows,fields)
 write_csv(OUT/'Corridor_V3_Endpoint_Research_Gaps.csv',gaps,['candidate_id','district_old','corridor_name','gap','recommended_action'])
 write_csv(OUT/'Corridor_V3_Geometry_QA.csv',qa,['candidate_id','district_old','corridor_name','geometry_status','flags','action'])
 meta={'candidate_count':len(rows),'by_district':dict(Counter(r['district_old'] for r in rows)),
 'candidate_with_draft_endpoints':sum(bool(r['start_lat']) for r in rows),'candidate_with_osm_geometry':sum(r['osm_geometry_status']!='NO_OSM_GEOMETRY' for r in rows),
 'endpoint_gaps':sum(x['gap']=='START_END_NOT_DEFINED' for x in gaps),
 'source_workbook':wbpath.name,'constraints':['No traffic volume inference','No auto-picked START/END','OSM geometry provisional until QA','Rent median only from historic clean independent usable samples (not recomputed here)','No scoring until comparable corridor evidence and geometry validated','Original district 5 selection remains independent of these corridor outputs']}
 (OUT/'Corridor_V3_Methodology.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
 if a.scan_osm:scan_osm(wb,OUT)
 print(json.dumps(meta,ensure_ascii=False,indent=2));print('Outputs:',OUT)

def scan_osm(wb,out):
 """Discover presence of old-corridor road names in OSM within GPS-derived area bounds.
 Never treats discovered geometry extent as defined study corridor.
 """
 try:import osmnx as ox
 except ImportError:raise SystemExit('Install osmnx: python -m pip install osmnx')
 points=wb_sheet(wb,'04_Market_Locations')
 # Determine available columns from actual workbook; hard failures preferred to wrong column guessing.
 print('OSM scan: checking market-location columns...')
 if points:print('Columns:',list(points[0])[:25])
 # Scanning requires an explicit bounding-box policy; avoid silently inferring district borders from competitor locations.
 print('OSM scan deferred: no defensible district/segment bounds configured. Fill corridor START/END before routing.')

if __name__=='__main__':main()
