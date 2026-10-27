"""iCare V4 - Discover OSM intersection candidates; NEVER auto-approve START/END.
Run in project root: python build_corridor_endpoint_candidates_V4.py
Requires: osmnx, networkx. Internet for OSM Overpass/Nominatim on first run.
Input: Data/Processed/Corridor_V3_Inventory_31.csv
Outputs: Data/Processed/Corridor_V4_Intersection_Candidates.csv
         Data/Processed/Corridor_V4_Endpoint_QA.csv
         Data/Processed/Corridor_V4_Run_Summary.json
"""
from __future__ import annotations
import argparse
import csv
import json
import math
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

import osmnx as ox

PLACE_QUERIES = {
    "Quận 12": ["Quận 12, Thành phố Hồ Chí Minh, Việt Nam", "District 12, Ho Chi Minh City, Vietnam"],
    "Bình Tân": ["Quận Bình Tân, Thành phố Hồ Chí Minh, Việt Nam", "Binh Tan District, Ho Chi Minh City, Vietnam"],
    "Bình Thạnh": ["Quận Bình Thạnh, Thành phố Hồ Chí Minh, Việt Nam", "Binh Thanh District, Ho Chi Minh City, Vietnam"],
}
# Additional historic / commonly used road labels. Each must be reviewed in QA.
ALIAS_CANDIDATES = {
    "Đỗ Mười": ["Đỗ Mười", "Quốc lộ 1", "Quốc lộ 1A", "QL1A"],
    "QL1 / Lê Đức Anh": ["Lê Đức Anh", "Quốc lộ 1", "Quốc lộ 1A", "QL1", "QL1A"],
    "Quốc lộ 13": ["Quốc lộ 13", "QL13"],
}

def normalize(s):
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = "".join(c for c in s if not unicodedata.combining(c)).replace("đ", "d").replace("Đ", "D")
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()

def edge_names(x):
    if isinstance(x, list):
        return [str(v).strip() for v in x if v]
    return [str(x).strip()] if x else []

def haversine_m(a, b):
    la1, lo1 = a; la2, lo2 = b
    x1, x2 = math.radians(la1), math.radians(la2)
    dlat, dlon = x2 - x1, math.radians(lo2-lo1)
    q = math.sin(dlat/2)**2 + math.cos(x1)*math.cos(x2)*math.sin(dlon/2)**2
    return 6371000 * 2 * math.asin(min(1, math.sqrt(q)))

def save_csv(path, columns, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        w=csv.DictWriter(f, fieldnames=columns, extrasaction='ignore'); w.writeheader(); w.writerows(records)

def get_graph(district):
    last = None
    for query in PLACE_QUERIES[district]:
        try:
            print(f"  OSM query: {query}", flush=True)
            # Old district boundaries may have disappeared after administrative changes.
            g=ox.graph_from_place(query, network_type='drive', simplify=True, retain_all=True)
            if len(g.nodes)>0 and len(g.edges)>0:
                return g,query
        except Exception as e:
            last = str(e)[:320]
            print(f"  Place lookup failed: {last}", flush=True)
    raise RuntimeError(f"Cannot retrieve OSM graph for {district}: {last}")

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--root',default='.', help='Project folder')
    p.add_argument('--all-23',action='store_true', help='Also search new Q7/Go Vap gaps; requires configuring place queries first')
    p.add_argument('--cluster-m',type=float,default=65.0)
    args=p.parse_args()
    root=Path(args.root).resolve(); processed=root/'Data'/'Processed'
    source=processed/'Corridor_V3_Inventory_31.csv'
    if not source.exists():
        raise SystemExit(f"Missing input: {source}\nRun build_corridor_pipeline_V3.py first.")
    with source.open(encoding='utf-8-sig', newline='') as f: rows=list(csv.DictReader(f))
    target=[r for r in rows if r['district_old'] in PLACE_QUERIES and r.get('endpoint_status')=='NEED_CORRIDOR_SEGMENT_DEFINITION']
    if len(target)!=15:
        print(f"WARNING: expected 15 old corridors but found {len(target)}; no fabricated records.")
    if args.all_23:
        print('NOTE: --all-23 is reserved; new district extraction not configured. Processing old 15 only.')
    ox.settings.use_cache=True
    # Bound Overpass concurrency and log which requests fail.
    candidates=[]; qa=[]; by_district=defaultdict(list)
    for r in target: by_district[r['district_old']].append(r)
    for district, roads in by_district.items():
        print(f"Downloading OSM network for {district} ...",flush=True)
        try: G,place_query=get_graph(district)
        except Exception as exc:
            for r in roads:
                qa.append(dict(candidate_id=r['candidate_id'],district_old=district,corridor_name=r['corridor_name'],status='OSM_DOWNLOAD_OR_BOUNDARY_FAILED',matched_edges=0,intersection_candidates=0,notes=str(exc)[:500]))
            continue
        print(f"  nodes={len(G.nodes)}, edges={len(G.edges)}",flush=True)
        # each node: names of connecting drivable streets, not simply nearby street labels
        incident=defaultdict(set)
        all_edges=[]
        for u,v,k,data in G.edges(keys=True,data=True):
            names=edge_names(data.get('name'))
            if not names: continue
            for name in names:
                incident[u].add(name); incident[v].add(name)
            all_edges.append((u,v,names))
        for r in roads:
            road=r['corridor_name']; alias=ALIAS_CANDIDATES.get(road,[road]); lookup={normalize(a) for a in alias}
            # exact normalized name only, no unchecked partial matches
            matched=[(u,v,names) for u,v,names in all_edges if lookup.intersection(normalize(n) for n in names)]
            matched_nodes={n for u,v,_ in matched for n in (u,v)}
            hits=[]
            for n in matched_nodes:
                others=sorted({name for name in incident[n] if normalize(name) not in lookup})
                if not others: continue
                nd=G.nodes[n]
                if 'y' not in nd or 'x' not in nd: continue
                road_names=sorted({name for name in incident[n] if normalize(name) in lookup})
                hits.append(dict(candidate_id=r['candidate_id'],district_old=district,corridor_name=road,
                                 latitude=float(nd['y']),longitude=float(nd['x']),
                                 osmid=str(n),matched_names='; '.join(road_names),
                                 crossing_names='; '.join(others),
                                 source='OSM_DRIVABLE_GRAPH_CONNECTED_NODE',
                                 method='shared_network_node_not_nearby_crossing',
                                 review_status='CANDIDATE_ONLY_NOT_ENDPOINT',
                                 osm_place_query=place_query))
            # Merge multiple OSM nodes representing same junction into clusters; preserve originals in notes.
            hits.sort(key=lambda x:(x['latitude'],x['longitude'],x['osmid']))
            clusters=[]
            for h in hits:
                found=None
                for group in clusters:
                    if haversine_m((h['latitude'],h['longitude']), (group[0]['latitude'],group[0]['longitude']))<=args.cluster_m:
                        found=group;break
                if found is None: clusters.append([h])
                else: found.append(h)
            for i,group in enumerate(clusters,1):
                anchor=group[0].copy()
                anchor['intersection_id']=f"{r['candidate_id']}-I{i:03d}"
                anchor['cluster_nodes']=len(group)
                anchor['crossing_names']='; '.join(sorted({name for h in group for name in h['crossing_names'].split('; ') if name}))
                anchor['matched_names']='; '.join(sorted({name for h in group for name in h['matched_names'].split('; ') if name}))
                anchor['alias_match_review']='YES' if normalize(road) not in {normalize(n) for n in anchor['matched_names'].split('; ')} else 'NO'
                candidates.append(anchor)
            if not matched: status='NO_MATCHING_OSM_ROAD_NAME'
            elif not clusters: status='ROAD_FOUND_NO_CONNECTED_NAMED_JUNCTIONS'
            elif len(clusters)<2: status='FEWER_THAN_TWO_JUNCTION_CANDIDATES'
            else: status='CANDIDATES_FOUND_NEED_SEGMENT_SELECTION'
            qa.append(dict(candidate_id=r['candidate_id'],district_old=district,corridor_name=road,status=status,
                           matched_edges=len(matched),intersection_candidates=len(clusters),
                           notes='Requires corridor-specific business scope/evidence; OSM does not establish best START/END. Aliases require review.' if road in ALIAS_CANDIDATES else 'Requires manual/analytical selection of business-relevant subsegment.'))
            print(f"  {r['candidate_id']} {road}: {len(matched)} matching edges; {len(clusters)} intersections; {status}",flush=True)
    ccols=['intersection_id','candidate_id','district_old','corridor_name','latitude','longitude','osmid','matched_names','crossing_names','cluster_nodes','alias_match_review','source','method','review_status','osm_place_query']
    qcols=['candidate_id','district_old','corridor_name','status','matched_edges','intersection_candidates','notes']
    save_csv(processed/'Corridor_V4_Intersection_Candidates.csv',ccols,candidates)
    save_csv(processed/'Corridor_V4_Endpoint_QA.csv',qcols,qa)
    summary=dict(old_corridors_requested=len(target),old_corridors_processed=len(qa),intersections_found=len(candidates),
      corridors_with_two_or_more_candidates=sum(int(q['intersection_candidates']>=2) for q in qa),
      districts_attempted=list(by_district),auto_selected_endpoints=0,
      outputs=['Corridor_V4_Intersection_Candidates.csv','Corridor_V4_Endpoint_QA.csv','Corridor_V4_Run_Summary.json'],
      methodology='OSM drive network shared nodes with exact normalized street names; 65m clustering; no traffic or ranking inference; no endpoint auto-selection; intersection candidates only')
    (processed/'Corridor_V4_Run_Summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
