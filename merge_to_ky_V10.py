"""Merge V7 intersection review and V9 Tô Ký candidates conservatively.
Read-only inputs. No endpoint selection. Python standard library only.
"""
from pathlib import Path
import csv, json, re, unicodedata

BASE = Path(__file__).resolve().parent
PROC = BASE / 'Data' / 'Processed'
if not (PROC/'Corridor_V7_Intersection_Review.csv').exists():
    PROC = BASE

V7=PROC/'Corridor_V7_Intersection_Review.csv'
V9=PROC/'Corridor_V9_To_Ky_Intersection_Candidates.csv'
for p in (V7,V9):
    if not p.exists(): raise SystemExit(f'Missing input: {p}')

def read_csv(path):
    with path.open('r',encoding='utf-8-sig',newline='') as f: return list(csv.DictReader(f))

def normalize(s):
    s=unicodedata.normalize('NFD', str(s).casefold())
    s=''.join(c for c in s if unicodedata.category(c)!='Mn')
    return re.sub(r'\s+',' ',s).strip()

rows=read_csv(V7); raw=read_csv(V9)
if not rows: raise SystemExit('V7 input empty')
headers=list(rows[0]); new=[]; rejected=[]
# Original GPS-derived Quận 12 box from V4 diagnostic; an evidence search window, NOT district boundary.
W,S,E,N=106.597215,10.812708,106.641567,10.881833
seen=set()
for row in raw:
    lat=float(row['latitude']); lon=float(row['longitude']); crossing=row['crossing_names'].strip()
    reasons=[]
    if not (S<=lat<=N and W<=lon<=E): reasons.append('OUTSIDE_Q12_GPS_BBOX')
    n=normalize(crossing)
    if re.search(r'\b(hem|ngo|ngach)\b',n): reasons.append('ALLEY_OR_LANE')
    if any(x in n for x in ('cau vuot','cau ','trunk_link','footbridge')): reasons.append('BRIDGE_OR_CONNECTOR')
    if not crossing: reasons.append('UNNAMED_CROSSING')
    # same OSM node may legitimately list distinct crossing road names: retain them separately
    key=(str(row['osmid']),n)
    if key in seen: reasons.append('DUPLICATE_NODE_AND_CROSSING')
    seen.add(key)
    if reasons:
        rejected.append({**row,'qa_reason':'|'.join(reasons)})
        continue
    out={c:'' for c in headers}
    out.update({'candidate_id':'Q12-TOKY','district_old':'Quận 12','corridor_name':'Tô Ký',
      'intersection_id':'Q12-TOKY-OSM-'+str(row['osmid']),
      'crossing_names':crossing,'latitude':str(lat),'longitude':str(lon),
      'crossing_class':'NAMED_CROSSING_UNVERIFIED','status':'CANDIDATE_NOT_VALIDATED',
      'suggested_role':'POTENTIAL_SEGMENT_LANDMARK_ONLY','osmid':str(row['osmid']),
      'source_phase':'V9_SCOPE_FILTERED','matched_names':row.get('matched_names',''),
      'source':row.get('source',''),'method':row.get('method',''),
      'review_status':'CANDIDATE_NOT_VALIDATED','source_osmid':str(row['osmid']),
      'endpoint_role':'NOT_SELECTED',
      'geometry_scope':'Q12_COMPETITOR_GPS_BBOX_NOT_ADMIN_BOUNDARY'})
    new.append(out)

merged=rows+new
PROC.mkdir(parents=True,exist_ok=True)
def write(name, fields, data):
    p=PROC/name
    with p.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(data)
    return str(p)

write('Corridor_V10_Intersection_Review.csv',headers,merged)
write('Corridor_V10_To_Ky_Excluded_QA.csv',list(raw[0])+['qa_reason'],rejected)
counts={}
for r in merged: counts[r['corridor_name']]=counts.get(r['corridor_name'],0)+1
summary={'v7_rows':len(rows),'v9_raw_rows':len(raw),'v9_retained_for_review':len(new),
 'v9_excluded_with_reasons':len(rejected),'merged_rows':len(merged),
 'corridors_with_candidates':len(counts),'to_ky_candidates':counts.get('Tô Ký',0),
 'endpoint_autoselected':0,'geographic_caveat':'GPS-based BBOX is not district boundary; review Tô Ký locations against actual road and business anchors before selecting endpoints.',
 'source_snapshot':'Local Geofabrik Vietnam PBF (V9)'}
(PROC/'Corridor_V10_Summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False,indent=2))
print('Output:',PROC)
