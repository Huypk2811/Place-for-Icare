"""iCare V12: Evidence QA gate. Standard library only; never edits source workbook.
Run from project root: python validate_corridor_evidence_V12.py
"""
from pathlib import Path
import csv, json, math

BASE = Path(__file__).resolve().parent
PROCESSED = BASE / 'Data' / 'Processed'
SOURCE = PROCESSED / 'Corridor_V11_Evidence_Audit.csv'
OPTIONS = PROCESSED / 'Corridor_V11_Endpoint_Review_Options.csv'
if not SOURCE.is_file():
    raise SystemExit(f'Missing input: {SOURCE}')

def readcsv(path):
    with path.open('r', encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))
def savecsv(path, rows, fields):
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore'); w.writeheader(); w.writerows(rows)
def num(v):
    try: return float(v) if v not in ('', None) else None
    except (ValueError,TypeError): return None

evidence = readcsv(SOURCE)
result=[]; flags=[]
for r in evidence:
    district, road = r.get('district_old',''),r.get('corridor_name','')
    n=num(r.get('clean_rent_n')); old=num(r.get('rent_median_million'))
    meets_count=n is not None and n >= 3
    status=('PENDING_SAMPLE_LEVEL_VERIFICATION' if meets_count else
            'INSUFFICIENT_CLEAN_SAMPLES' if n is not None else 'MISSING_CLEAN_COUNT')
    # Even if n>=3, V11 alone cannot prove independent, current or usability.
    row=dict(r)
    row.update(rent_median_raw_historic=r.get('rent_median_million',''),
               rent_median_validated='', rent_count_gate='PASS' if meets_count else 'FAIL',
               rent_qa_status=status,
               segment_evidence_status='CORRIDOR_LEVEL_ONLY_NOT_SEGMENT_VALIDATED',
               site_score_eligible='NO')
    result.append(row)
    if old is not None and not meets_count:
        flags.append({'district_old':district,'corridor_name':road,
                      'issue':'HISTORIC_MEDIAN_NOT_ELIGIBLE','clean_rent_n':r.get('clean_rent_n',''),
                      'historic_median':r.get('rent_median_million',''),
                      'action':'Do not use median. Inspect individual listings and reconcile previous locked sample set.'})
    if meets_count:
        flags.append({'district_old':district,'corridor_name':road,
                      'issue':'VERIFY_LISTING_INDEPENDENCE_AND_SCOPE','clean_rent_n':r.get('clean_rent_n',''),
                      'historic_median':r.get('rent_median_million',''),
                      'action':'Check clean_current+usable_current, duplicates, listing date, exact address before validating median.'})

PROCESSED.mkdir(parents=True,exist_ok=True)
savecsv(PROCESSED/'Corridor_V12_Evidence_QA.csv',result,list(result[0]) if result else [])
savecsv(PROCESSED/'Corridor_V12_Rent_Review_Queue.csv',flags,['district_old','corridor_name','issue','clean_rent_n','historic_median','action'])
options=readcsv(OPTIONS) if OPTIONS.is_file() else []
for r in options:
    r['segment_evidence_status']='UNVERIFIED'
    r['rent_segment_match']='NOT_GEOLOCATED'
    r['endpoint_decision_status']='REVIEW_ONLY'
    r['spatial_geometry_status']='NEEDS_OSM_ROUTE_QA'
if options: savecsv(PROCESSED/'Corridor_V12_Segment_Review_Queue.csv',options,list(options[0]))
summary={'corridors_audited':len(result),'historic_medians_blocked_due_to_n_below_3':sum(f['issue']=='HISTORIC_MEDIAN_NOT_ELIGIBLE' for f in flags),
         'rent_rows_with_n_ge_3_pending_listing_verification':sum(f['issue']=='VERIFY_LISTING_INDEPENDENCE_AND_SCOPE' for f in flags),
         'review_segments':len(options),'validated_segment_endpoints':0,
         'no_inputs_modified':True,'note':'Only a QA gate; no rent median or business score is validated by this script.'}
(PROCESSED/'Corridor_V12_Run_Summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False,indent=2))
print(f'Outputs: {PROCESSED}')
