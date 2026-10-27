from pathlib import Path
import pandas as pd
import re

ROOT=Path(__file__).resolve().parent
IN=ROOT/'Data'/'Processed'
if not (IN/'Corridor_V4_Intersection_Candidates.csv').exists():
    IN=ROOT
    a=IN/'Corridor_V4_Intersection_Candidates(1).csv'
    b=IN/'Corridor_V4_Endpoint_QA(1).csv'
else:
    a=IN/'Corridor_V4_Intersection_Candidates.csv'
    b=IN/'Corridor_V4_Endpoint_QA.csv'
out=IN
raw=pd.read_csv(a).fillna('')
qa=pd.read_csv(b)

def classify(s):
    s=str(s).strip().lower()
    if not s:return 'UNNAMED'
    if re.search(r'(^|\W)(hẻm|hem|ngõ|ngo|ngách|kiệt)(\W|$)',s):return 'ALLEY'
    if 'cầu' in s or 'hầm' in s or 'vượt' in s:return 'BRIDGE_OR_GRADE_SEPARATED'
    if re.search(r'^(đường số|đường sô|đường \d+|đường d\d+)',s):return 'NUMBERED_STREET'
    return 'NAMED_CROSSING'

raw['crossing_class']=raw.crossing_names.map(classify)
raw['distance_km']=pd.to_numeric(raw.nearest_observed_gps_km,errors='coerce')
raw['candidate_priority']=raw.crossing_class.map({'NAMED_CROSSING':1,'NUMBERED_STREET':2,'UNNAMED':3,'BRIDGE_OR_GRADE_SEPARATED':4,'ALLEY':5})
# Discovers review anchors, not a START/END selection or score.
review=raw[raw.crossing_class.isin(['NAMED_CROSSING','NUMBERED_STREET'])].copy()
review=review.sort_values(['candidate_id','candidate_priority','distance_km','intersection_id'])
# Filter coordinate duplicates at approx 15m grid only for review (retains raw data)
review['grid_lat']=pd.to_numeric(review.latitude).round(4)
review['grid_lon']=pd.to_numeric(review.longitude).round(4)
review=review.drop_duplicates(['candidate_id','crossing_names','grid_lat','grid_lon'])
review['review_rank_within_corridor']=review.groupby('candidate_id').cumcount()+1
review['status']='CANDIDATE_NOT_VALIDATED'
review['suggested_role']='POTENTIAL_SEGMENT_LANDMARK_ONLY'
columns=['candidate_id','district_old','corridor_name','intersection_id','crossing_names','latitude','longitude','distance_km','crossing_class','review_rank_within_corridor','status','suggested_role','alias_match_review','osmid']
review[columns].to_csv(out/'Corridor_V5_Named_Intersection_Review.csv',index=False,encoding='utf-8-sig')
counts=raw.groupby('candidate_id').agg(raw_intersections=('intersection_id','size'),named_crossings=('crossing_class',lambda x:(x=='NAMED_CROSSING').sum()),alleys=('crossing_class',lambda x:(x=='ALLEY').sum()),bridges=('crossing_class',lambda x:(x=='BRIDGE_OR_GRADE_SEPARATED').sum())).reset_index()
summary=qa.merge(counts,on='candidate_id',how='left').fillna({'raw_intersections':0,'named_crossings':0,'alleys':0,'bridges':0})
summary=summary.merge(review.groupby('candidate_id').size().rename('review_candidates').reset_index(),on='candidate_id',how='left').fillna({'review_candidates':0})
summary['next_action']=summary.apply(lambda r:'EXPAND_OSM_SEARCH_AREA_AND_ALIASES' if r.candidates_found==0 else 'REVIEW_NAMED_CROSSINGS_AND_RESEARCH_ANCHORS',axis=1)
summary.to_csv(out/'Corridor_V5_Coverage_Gaps.csv',index=False,encoding='utf-8-sig')
print({'all_intersections':len(raw),'named_and_numbered_review_candidates':len(review),'corridors_with_candidates':int((summary.review_candidates>0).sum()),'corridors_missing':summary.loc[summary.candidates_found==0,'corridor_name'].tolist(),'output':str(out)})
