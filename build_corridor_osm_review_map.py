from pathlib import Path
import json, html
import pandas as pd
import folium

ROOT=Path(__file__).resolve().parent
RAW=ROOT/'Data'/'Raw'
OUT=ROOT/'Data'/'Processed'
# Also permits running beside supplied CSV/GeoJSON files
roads=next((p for p in [OUT/'Corridor_OSM_Roads_REVIEW.geojson',ROOT/'Corridor_OSM_Roads_REVIEW(1).geojson'] if p.exists()),None)
segments=next((p for p in [RAW/'iCare_8_Corridor_Segments_DRAFT.csv',ROOT/'iCare_8_Corridor_Segments_DRAFT.csv'] if p.exists()),None)
if roads is None or segments is None:
    raise FileNotFoundError('Need Corridor_OSM_Roads_REVIEW.geojson in Data/Processed and iCare_8_Corridor_Segments_DRAFT.csv in Data/Raw')
geo=json.loads(roads.read_text(encoding='utf-8-sig'))
sdf=pd.read_csv(segments,encoding='utf-8-sig')
summary_path=OUT/'Corridor_OSM_Summary.csv'
qa_path=OUT/'Corridor_OSM_QA.csv'
sm={x['corridor_id']:x for x in pd.read_csv(summary_path).to_dict('records')} if summary_path.exists() else {}
qm={x['corridor_id']:str(x['details']) for x in pd.read_csv(qa_path).to_dict('records')} if qa_path.exists() else {}
by_name={(r.district_old,r.corridor_name):r for r in sdf.itertuples(index=False)}
mp = folium.Map(
    location=[10.786, 106.690],
    zoom_start=12,
    tiles=None,
    control_scale=True
)

folium.TileLayer(
    tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
    attr="Tiles © Esri and contributors",
    name="Esri World Street Map",
    overlay=False,
    control=True
).add_to(mp)
colors={'MIXED_NETWORK_NEEDS_VISUAL_QA':'#c77700','REVIEW_REQUIRED':'#b21f36','PROVISIONAL_REVIEW':'#2571c6'}
fgs={}
for feature in geo['features']:
    p=feature['properties'];cid=p['corridor_id'];dis=p['district_old'];name=p['corridor_name'];status=p.get('geometry_status','UNKNOWN')
    if dis not in fgs:
        fgs[dis]=folium.FeatureGroup(name=dis,show=True)
        fgs[dis].add_to(mp)
    color=colors.get(status,'#666666')
    coords=feature['geometry']['coordinates']
    if feature['geometry']['type']=='LineString': lines=[coords]
    else: lines=coords
    path=[[(lat,lon) for lon,lat in line] for line in lines]
    q=qm.get(cid,'No explicit QA flag (still requires map review)')
    popup=(f'<b>{html.escape(cid)} | {html.escape(name)}</b><br>Status: {html.escape(status)}'
       +f'<br>OSM length: {p.get("route_length_km", "?")} km<br>QA: {html.escape(q)}')
    for line in path:
        folium.PolyLine(line,color=color,weight=6,opacity=.8,tooltip=f'{cid} {name}',popup=folium.Popup(popup,max_width=360)).add_to(fgs[dis])
    s=by_name.get((dis,name))
    if s is not None:
        for desc,lat,lon in [('START',s.start_lat,s.start_lon),('END',s.end_lat,s.end_lon)]:
            folium.CircleMarker((lat,lon),radius=5,color=color,fill=True,fill_opacity=1,
                tooltip=f'{cid} {desc}',popup=f'{cid} {name} {desc}').add_to(fgs[dis])
folium.LayerControl(collapsed=False).add_to(mp)
mp.get_root().html.add_child(folium.Element('<div style="position:fixed;bottom:25px;left:25px;z-index:9999;background:white;padding:12px;border:1px solid #aaa;font:13px Arial;max-width:310px"><b>iCare corridor OSM — REVIEW ONLY</b><br><span style="color:#c77700">■</span> Mixed-network fallback<br><span style="color:#b21f36">■</span> Intersection unconfirmed<br><span style="color:#2571c6">■</span> Provisional named-road<br>Verify route and crossings visually. Road shape is not traffic volume.</div>'))
OUT.mkdir(parents=True,exist_ok=True)
target=OUT/'Corridor_OSM_Visual_QA.html';mp.save(str(target));print(f'Created: {target} | {len(geo["features"])} features')
