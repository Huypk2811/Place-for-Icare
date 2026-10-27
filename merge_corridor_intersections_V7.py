"""Merge V5 reviewed intersections with V6 expanded OSM candidates.
Does NOT select START/END or score corridors. Requires pandas.
Run from project root: python merge_corridor_intersections_V7.py
"""
from pathlib import Path
import json
import re
import unicodedata
import pandas as pd

ROOT = Path(__file__).resolve().parent
FOLDER = ROOT / 'Data' / 'Processed'
V5 = FOLDER / 'Corridor_V5_Named_Intersection_Review.csv'
V6 = FOLDER / 'Corridor_V6_Intersection_Candidates.csv'

for p in (V5, V6):
    if not p.is_file():
        raise SystemExit(f'MISSING INPUT: {p}\nRun V5/V6 first; no files were overwritten.')

v5 = pd.read_csv(V5, encoding='utf-8-sig').fillna('')
v6 = pd.read_csv(V6, encoding='utf-8-sig').fillna('')
required = {'candidate_id','district_old','corridor_name','latitude','longitude','crossing_names'}
for name, frame in [('V5',v5),('V6',v6)]:
    missing=required-set(frame.columns)
    if missing: raise SystemExit(f'{name}: missing columns {sorted(missing)}')

def crossing_class(s):
    s=str(s).strip().lower()
    if not s: return 'UNNAMED'
    if re.search(r'(^|\W)(hẻm|hem|ngõ|ngo|ngách|kiệt)(\W|$)',s): return 'ALLEY'
    if any(x in s for x in ('cầu','hầm','vượt')): return 'BRIDGE_OR_GRADE_SEPARATED'
    if re.search(r'^(đường số|đường sô|đường \d+|đường d\d+)',s): return 'NUMBERED_STREET'
    return 'NAMED_CROSSING'

def normalized(s):
    s=unicodedata.normalize('NFD', str(s).lower().strip())
    s=''.join(c for c in s if unicodedata.category(c)!='Mn').replace('đ','d')
    return re.sub(r'\s+',' ',s)

# V5 already filtered, but V6 must use the same first-pass eligibility.
v6['crossing_class']=v6['crossing_names'].map(crossing_class)
v6_filtered=v6[v6['crossing_class'].isin(['NAMED_CROSSING','NUMBERED_STREET'])].copy()
v5['source_phase']='V5';v6_filtered['source_phase']='V6'
allrows=pd.concat([v5,v6_filtered],ignore_index=True,sort=False)
allrows['latitude']=pd.to_numeric(allrows.latitude,errors='coerce')
allrows['longitude']=pd.to_numeric(allrows.longitude,errors='coerce')
bad=allrows.latitude.isna() | allrows.longitude.isna() | ~allrows.latitude.between(-90,90) | ~allrows.longitude.between(-180,180)
if bad.any(): raise SystemExit(f'Invalid coordinates found: {int(bad.sum())}; inspect input data.')
allrows['crossing_normalized']=allrows.crossing_names.map(normalized)
allrows['grid_lat']=allrows.latitude.round(4)
allrows['grid_lon']=allrows.longitude.round(4)
allrows['source_osmid']=allrows['osmid'].astype(str) if 'osmid' in allrows else ''
# Preserve IDs of OSM nodes when possible; otherwise dedup only exact small grid + same crossing name.
allrows['dedup_key']=allrows.apply(lambda r: f"{r.candidate_id}|osm:{r.source_osmid}" if r.source_osmid.strip() and r.source_osmid.lower() not in ('nan','none') else f"{r.candidate_id}|coord:{r.grid_lat:.4f}|{r.grid_lon:.4f}|{r.crossing_normalized}",axis=1)
allrows=allrows.sort_values(['candidate_id','source_phase','crossing_normalized'])
merged=allrows.drop_duplicates('dedup_key',keep='first').copy()
merged['review_status']='CANDIDATE_NOT_VALIDATED'
merged['endpoint_role']='NOT_SELECTED'
merged['geometry_scope']='GPS_BBOX_NOT_DISTRICT_BOUNDARY'
merged=merged.drop(columns=['grid_lat','grid_lon','crossing_normalized','dedup_key'],errors='ignore')

# Explicit fixed 15 corridor roster; do not infer missing corridors from partial results.
roster=[('Q12-01','Quận 12','Đỗ Mười'),('Q12-02','Quận 12','Lê Văn Khương'),('Q12-03','Quận 12','Nguyễn Ảnh Thủ'),('Q12-04','Quận 12','Tô Ký'),('Q12-05','Quận 12','Hà Huy Giáp'),('BT-01','Bình Tân','Kinh Dương Vương'),('BT-02','Bình Tân','Quốc lộ 1 / Lê Đức Anh'),('BT-03','Bình Tân','Tên Lửa'),('BT-04','Bình Tân','Tân Kỳ Tân Quý'),('BT-05','Bình Tân','Võ Trần Chí'),('BTH-01','Bình Thạnh','Xô Viết Nghệ Tĩnh'),('BTH-02','Bình Thạnh','Quốc lộ 13'),('BTH-03','Bình Thạnh','Đinh Bộ Lĩnh'),('BTH-04','Bình Thạnh','Nguyễn Xí'),('BTH-05','Bình Thạnh','Nơ Trang Long')]
roster_df=pd.DataFrame(roster,columns=['candidate_id','district_old','corridor_name'])
unknown=set(merged.candidate_id)-set(roster_df.candidate_id)
if unknown: raise SystemExit(f'Unexpected candidate IDs: {sorted(unknown)}; check version/roster.')
counts=merged.groupby('candidate_id').size().rename('candidate_n').reset_index()
phase_counts=merged.pivot_table(index='candidate_id',columns='source_phase',values='latitude',aggfunc='size',fill_value=0).reset_index()
summary=roster_df.merge(counts,on='candidate_id',how='left').merge(phase_counts,on='candidate_id',how='left')
for name in ['candidate_n','V5','V6']:
    if name not in summary: summary[name]=0
    summary[name]=summary[name].fillna(0).astype(int)
summary['status']=summary.candidate_n.map(lambda n:'INTERSECTIONS_FOUND_REVIEW' if n else 'NO_INTERSECTIONS_RESEARCH_REQUIRED')
summary['next_action']=summary.candidate_n.map(lambda n:'CROSSCHECK_WITH_HISTORIC_ANCHORS_AND_CORRIDOR_SCOPE' if n else 'CHECK_OSM_ALIASES_AND_ROAD_SCOPE_FOR_TO_KY')
merged.to_csv(FOLDER/'Corridor_V7_Intersection_Review.csv',index=False,encoding='utf-8-sig')
summary.to_csv(FOLDER/'Corridor_V7_Coverage_QA.csv',index=False,encoding='utf-8-sig')
report={'corridors_total':15,'corridors_with_candidates':int((summary.candidate_n>0).sum()),'corridors_without_candidates':summary.loc[summary.candidate_n==0,'corridor_name'].tolist(),'v5_rows':len(v5),'v6_rows_raw':len(v6),'v6_rows_after_consistent_filter':len(v6_filtered),'merged_candidate_rows':len(merged),'auto_selected_endpoints':0,'note':'Review candidates only; not administrative coverage, not traffic, no rent or site score.'}
(FOLDER/'Corridor_V7_Run_Summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))
