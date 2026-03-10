# heigit_dashboard.py
# One-tab professional dashboard with demographic inequality analysis
# Updated with:
# - Regional average benchmark on all plots
# - Remote high-resolution country boundaries from GitHub
# - Satellite basemap via ArcGIS imagery tiles
# - Fix for PyDeck rendering artifact
# - Auto-zoom to selected region
# - Professional floating continuous colorbar legend
#
# Run:
#   streamlit run heigit_dashboard.py
#
# Files expected in same directory:
#   - heigit_access_indicators_ADM0_ALL.xlsx
#   - Economies.xlsx

import os
import copy
import requests
import pandas as pd
import numpy as np
import streamlit as st
import plotly.express as px
import pydeck as pdk

st.set_page_config(page_title="Asia-Pacific Access Dashboard", layout="wide")

# ----------------------------------------------------
# FILES
# ----------------------------------------------------
DATA_FILE = "heigit_access_indicators_ADM0_ALL.xlsx"
ECON_FILE = "Economies.xlsx"

# Remote high-resolution boundaries (no local download needed)
BOUNDARY_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
    "master/geojson/ne_50m_admin_0_countries.geojson"
)

ISO_COL = "country"
REGION_COL = "economy_ato_subgroup"
ECON_ISO_COL = "economy"

# ----------------------------------------------------
# INDICATOR OPTIONS
# ----------------------------------------------------
HOSP_OPTIONS = {
    "30 min": ("pop_30min_hospital_pop", "pop_30min_hospital_share"),
    "60 min": ("pop_60min_hospital_pop", "pop_60min_hospital_share"),
    "90 min": ("pop_90min_hospital_pop", "pop_90min_hospital_share"),
    "120 min": ("pop_120min_hospital_pop", "pop_120min_hospital_share"),
}

SCHOOL_OPTIONS = {
    "5 km": ("pop_5km_school_pop", "pop_5km_school_share"),
    "10 km": ("pop_10km_school_pop", "pop_10km_school_share"),
    "20 km": ("pop_20km_school_pop", "pop_20km_school_share"),
    "50 km": ("pop_50km_school_pop", "pop_50km_school_share"),
}

HOSP_GAP_OPTIONS = {
    ">60 min": ("pop_beyond_60min_hospital_pop", "pop_beyond_60min_hospital_share"),
    ">90 min": ("pop_>90min_hospital_pop", "pop_>90min_hospital_share"),
    ">120 min": ("pop_>120min_hospital_pop", "pop_>120min_hospital_share"),
}

SCHOOL_GAP_FROM_WITHIN = {
    ">10 km": "pop_10km_school_share",
    ">20 km": "pop_20km_school_share",
    ">50 km": "pop_50km_school_share",
}

DEMOGRAPHIC_OPTIONS = {
    "Children under 5": ("under5_gap_60min_hospital_pop", "under5_gap_60min_hospital_share"),
    "Women of childbearing age": ("women_childbearing_gap_60min_hospital_pop", "women_childbearing_gap_60min_hospital_share"),
    "Elderly population": ("elderly_gap_60min_hospital_pop", "elderly_gap_60min_hospital_share"),
}

# ----------------------------------------------------
# HELPERS
# ----------------------------------------------------
def safe_sum(s):
    return float(pd.to_numeric(s, errors="coerce").fillna(0).sum())

def safe_mean(s):
    s = pd.to_numeric(s, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    return float(s.mean()) if len(s) else np.nan

def fmt_int(x):
    if pd.isna(x):
        return "—"
    return f"{int(round(float(x))):,}"

def fmt_pct(x):
    if pd.isna(x):
        return "—"
    return f"{float(x) * 100:,.1f}%"

def plot_height_for_n(n, base=220, per_row=18, max_h=1400):
    return int(min(max_h, base + per_row * max(1, n)))

def add_regional_avg_line(fig, avg_pct, label="Regional average"):
    if pd.notna(avg_pct):
        fig.add_vline(
            x=avg_pct,
            line_width=2,
            line_dash="dash",
            line_color="crimson"
        )
        fig.add_annotation(
            x=avg_pct,
            y=1.02,
            xref="x",
            yref="paper",
            text=f"{label}: {avg_pct:,.1f}%",
            showarrow=False,
            font=dict(color="crimson", size=12),
            bgcolor="rgba(255,255,255,0.90)"
        )
    return fig

def hex_to_rgb(hex_color):
    hex_color = hex_color.lstrip("#")
    return [int(hex_color[i:i+2], 16) for i in (0, 2, 4)]

def lerp(a, b, t):
    return a + (b - a) * t

def color_scale_viridis(v):
    if pd.isna(v):
        return [160, 160, 160, 60]

    v = max(0, min(1, float(v)))
    stops = [
        (0.00, "#440154"),
        (0.25, "#3b528b"),
        (0.50, "#21918c"),
        (0.75, "#5ec962"),
        (1.00, "#fde725"),
    ]

    for i in range(len(stops) - 1):
        v0, c0 = stops[i]
        v1, c1 = stops[i + 1]
        if v0 <= v <= v1:
            t = (v - v0) / (v1 - v0) if v1 > v0 else 0
            rgb0 = hex_to_rgb(c0)
            rgb1 = hex_to_rgb(c1)
            rgb = [int(lerp(rgb0[j], rgb1[j], t)) for j in range(3)]
            return rgb + [175]

    return [160, 160, 160, 60]

@st.cache_data(show_spinner=False)
def load_access(path):
    df = pd.read_excel(path, sheet_name="ADM0_indicators")
    df[ISO_COL] = df[ISO_COL].astype(str).str.upper().str.strip()
    return df

@st.cache_data(show_spinner=False)
def load_econ(path):
    econ = pd.read_excel(path, sheet_name=0)
    econ = econ[[ECON_ISO_COL, REGION_COL]].copy()
    econ[ECON_ISO_COL] = econ[ECON_ISO_COL].astype(str).str.upper().str.strip()
    return econ

@st.cache_data(show_spinner=False)
def load_boundaries(url):
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    return r.json()

def get_feature_iso(props):
    for c in ["ISO_A3", "ADM0_A3", "iso3", "country", "SU_A3", "GU_A3"]:
        if c in props and props[c]:
            return str(props[c]).upper().strip()
    return None

def attach_values_to_geojson(geojson, value_map, label_map=None):
    for feat in geojson.get("features", []):
        props = feat.get("properties", {})
        iso = get_feature_iso(props)
        value = value_map.get(iso, np.nan)

        props["country_code"] = iso or ""
        props["country_name"] = (label_map.get(iso, iso) if label_map else iso) or ""
        props["value"] = None if pd.isna(value) else float(value)
        props["value_pct"] = None if pd.isna(value) else round(float(value) * 100, 1)
        props["fill_color"] = color_scale_viridis(value)

        feat["properties"] = props
    return geojson

def get_region_geojson(geojson, iso_set):
    features = []
    for feat in geojson.get("features", []):
        iso = get_feature_iso(feat.get("properties", {}))
        if iso in iso_set:
            features.append(feat)
    return {"type": "FeatureCollection", "features": features}

def extract_coords_from_geometry(geom):
    coords = []

    def walk(x):
        if isinstance(x, (list, tuple)):
            if len(x) >= 2 and isinstance(x[0], (int, float)) and isinstance(x[1], (int, float)):
                coords.append((float(x[0]), float(x[1])))
            else:
                for item in x:
                    walk(item)

    if geom and "coordinates" in geom:
        walk(geom["coordinates"])
    return coords

def compute_view_state_from_geojson(geojson, default_lat=15, default_lon=105, default_zoom=2.2):
    xs, ys = [], []
    for feat in geojson.get("features", []):
        geom = feat.get("geometry", {})
        for x, y in extract_coords_from_geometry(geom):
            if -180 <= x <= 180 and -90 <= y <= 90:
                xs.append(x)
                ys.append(y)

    if not xs or not ys:
        return pdk.ViewState(
            latitude=default_lat,
            longitude=default_lon,
            zoom=default_zoom,
            pitch=0,
            bearing=0
        )

    minx, maxx = min(xs), max(xs)
    miny, maxy = min(ys), max(ys)
    center_lon = (minx + maxx) / 2
    center_lat = (miny + maxy) / 2
    span = max(maxx - minx, maxy - miny)

    if span > 140:
        zoom = 1.3
    elif span > 90:
        zoom = 1.8
    elif span > 60:
        zoom = 2.3
    elif span > 35:
        zoom = 3.0
    elif span > 20:
        zoom = 3.8
    elif span > 10:
        zoom = 4.6
    else:
        zoom = 5.3

    return pdk.ViewState(
        latitude=center_lat,
        longitude=center_lon,
        zoom=zoom,
        pitch=0,
        bearing=0
    )

# ----------------------------------------------------
# FILE CHECKS
# ----------------------------------------------------
if not os.path.exists(DATA_FILE):
    st.error("Missing access dataset")
    st.stop()

if not os.path.exists(ECON_FILE):
    st.error("Missing Economies.xlsx")
    st.stop()

# ----------------------------------------------------
# LOAD DATA
# ----------------------------------------------------
df_all = load_access(DATA_FILE)
econ = load_econ(ECON_FILE)
geojson_boundaries = load_boundaries(BOUNDARY_URL)

df_all = df_all.merge(
    econ.rename(columns={ECON_ISO_COL: ISO_COL}),
    on=ISO_COL,
    how="left"
)
df_all[REGION_COL] = df_all[REGION_COL].fillna("Unknown")

# ----------------------------------------------------
# HEADER
# ----------------------------------------------------
st.title("Access to Essential Services in Asia-Pacific")

st.caption(
    "Dashboard summarizing accessibility to hospitals and schools, "
    "including geographic distribution, rankings, regional comparisons, "
    "accessibility gaps, and demographic inequalities."
)

# ----------------------------------------------------
# FILTERS
# ----------------------------------------------------
c1, c2, c3, c4 = st.columns([1.2, 1.2, 1.2, 1.4])

with c1:
    region = st.selectbox(
        "ATO subregion",
        ["All"] + sorted(df_all[REGION_COL].dropna().unique()),
        key="region"
    )

with c2:
    indicator = st.selectbox(
        "Primary indicator",
        ["Hospital travel time", "School distance"],
        key="indicator"
    )

with c3:
    if indicator == "Hospital travel time":
        threshold = st.selectbox("Threshold", list(HOSP_OPTIONS.keys()), index=1)
        pop_col, share_col = HOSP_OPTIONS[threshold]
        total_col = "hospital_total_pop_est"
        title_primary = f"Hospital access within {threshold}"
    else:
        threshold = st.selectbox("Threshold", list(SCHOOL_OPTIONS.keys()), index=1)
        pop_col, share_col = SCHOOL_OPTIONS[threshold]
        total_col = "edu_total_pop_est"
        title_primary = f"School access within {threshold}"

with c4:
    show_mode = st.radio(
        "Ranking bars",
        ["Show all countries", "Top N only"],
        horizontal=True
    )
    top_n = None
    if show_mode == "Top N only":
        top_n = st.slider("N", 5, 60, 25)

# ----------------------------------------------------
# FILTER REGION
# ----------------------------------------------------
df = df_all.copy()
if region != "All":
    df = df[df[REGION_COL] == region].copy()

# ----------------------------------------------------
# KEY METRICS
# ----------------------------------------------------
covered = safe_sum(df.get(pop_col))
total = safe_sum(df.get(total_col))
share_weighted = covered / total if total > 0 else np.nan

tmp_share = pd.to_numeric(df.get(share_col), errors="coerce")
regional_avg_share = safe_mean(tmp_share)

best_country = df.loc[tmp_share.idxmax(), ISO_COL] if tmp_share.notna().any() else "—"
worst_country = df.loc[tmp_share.idxmin(), ISO_COL] if tmp_share.notna().any() else "—"

k1, k2, k3, k4 = st.columns(4)
k1.metric("Population within threshold", fmt_int(covered))
k2.metric("Population beyond threshold", fmt_int(total - covered))
k3.metric("Share with access (weighted)", fmt_pct(share_weighted))
k4.metric("Lowest access country", worst_country)

st.divider()

# ----------------------------------------------------
# MAP + OVERLAID LEGEND
# ----------------------------------------------------
st.subheader(title_primary)

map_df = df[[ISO_COL]].copy()
map_df["share"] = pd.to_numeric(df.get(share_col), errors="coerce")
map_df["pop_within"] = pd.to_numeric(df.get(pop_col), errors="coerce")
map_df["region"] = df[REGION_COL]

value_map = dict(zip(map_df[ISO_COL], map_df["share"]))
label_map = dict(zip(map_df[ISO_COL], map_df[ISO_COL]))

geojson_for_map = attach_values_to_geojson(
    copy.deepcopy(geojson_boundaries),
    value_map=value_map,
    label_map=label_map
)

iso_set = set(map_df[ISO_COL].dropna().astype(str).str.upper())
region_geojson = get_region_geojson(geojson_for_map, iso_set)

view_state = (
    compute_view_state_from_geojson(region_geojson)
    if region != "All"
    else pdk.ViewState(latitude=15, longitude=105, zoom=2.2, pitch=0, bearing=0)
)

tooltip = {
    "html": """
    <div style="font-family:Arial; font-size:13px;">
        <b>{country_name}</b><br/>
        ISO3: {country_code}<br/>
        Share with access: {value_pct}%
    </div>
    """,
    "style": {
        "backgroundColor": "rgba(20,20,20,0.9)",
        "color": "white"
    }
}

tile_layer = pdk.Layer(
    "TileLayer",
    data="https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    min_zoom=0,
    max_zoom=19,
    tile_size=256,
    opacity=1.0,
)

fill_layer = pdk.Layer(
    "GeoJsonLayer",
    data=geojson_for_map,
    pickable=True,
    stroked=True,
    filled=True,
    extruded=False,
    wireframe=False,
    get_fill_color="properties.fill_color",
    get_line_color=[255, 255, 255, 160],
    line_width_min_pixels=0.8,
)

outline_layer = pdk.Layer(
    "GeoJsonLayer",
    data=geojson_for_map,
    pickable=False,
    stroked=True,
    filled=False,
    get_line_color=[20, 20, 20, 180],
    line_width_min_pixels=1,
)

deck = pdk.Deck(
    layers=[tile_layer, fill_layer, outline_layer],
    initial_view_state=view_state,
    tooltip=tooltip,
    map_style=None,
    parameters={"depthTest": False}
)

st.pydeck_chart(deck, use_container_width=True)

# ----- legend values -----
legend_vals = pd.to_numeric(map_df["share"], errors="coerce").dropna()
if len(legend_vals):
    legend_min = float(legend_vals.min()) * 100
    legend_max = float(legend_vals.max()) * 100
else:
    legend_min = 0.0
    legend_max = 100.0

if abs(legend_max - legend_min) < 1e-9:
    legend_min = max(0.0, legend_min - 5)
    legend_max = min(100.0, legend_max + 5)

ticks = np.linspace(legend_min, legend_max, 5)

legend_html = f"""
<style>
.map-legend-fixed {{
    position: relative;
    width: 100%;
    height: 0;
}}
.map-legend-fixed .legend-box {{
    position: absolute;
    right: 18px;
    top: -340px;
    width: 155px;
    background: rgba(255,255,255,0.96);
    border: 1px solid #d0d0d0;
    border-radius: 8px;
    padding: 12px 12px 10px 12px;
    box-shadow: 0 3px 10px rgba(0,0,0,0.18);
    font-family: Arial, sans-serif;
    font-size: 12px;
    z-index: 999;
}}
.map-legend-fixed .legend-title {{
    font-weight: 700;
    margin-bottom: 8px;
}}
.map-legend-fixed .legend-wrap {{
    display: flex;
    align-items: stretch;
}}
.map-legend-fixed .legend-bar {{
    width: 18px;
    height: 160px;
    border-radius: 4px;
    border: 1px solid #aaa;
    background: linear-gradient(
        to top,
        #440154 0%,
        #3b528b 25%,
        #21918c 50%,
        #5ec962 75%,
        #fde725 100%
    );
}}
.map-legend-fixed .legend-ticks {{
    height: 160px;
    margin-left: 10px;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
}}
</style>

<div class="map-legend-fixed">
  <div class="legend-box">
    <div class="legend-title">Share with access (%)</div>
    <div class="legend-wrap">
      <div class="legend-bar"></div>
      <div class="legend-ticks">
        <div>{ticks[4]:.1f}%</div>
        <div>{ticks[3]:.1f}%</div>
        <div>{ticks[2]:.1f}%</div>
        <div>{ticks[1]:.1f}%</div>
        <div>{ticks[0]:.1f}%</div>
      </div>
    </div>
  </div>
</div>
"""

st.markdown(legend_html, unsafe_allow_html=True)

if pd.notna(regional_avg_share):
    st.caption(f"Regional average share with access: {regional_avg_share * 100:,.1f}%")

st.divider()

# ----------------------------------------------------
# COUNTRY RANKING
# ----------------------------------------------------
st.subheader("Country ranking")

rank_df = map_df.dropna(subset=["share"]).sort_values("share", ascending=False).copy()
if top_n:
    rank_df = rank_df.head(top_n)

rank_df["share_pct"] = rank_df["share"] * 100
rank_avg_pct = regional_avg_share * 100 if pd.notna(regional_avg_share) else np.nan

fig_rank = px.bar(
    rank_df,
    x="share_pct",
    y=ISO_COL,
    orientation="h"
)

fig_rank.update_layout(
    height=plot_height_for_n(len(rank_df)),
    yaxis={"categoryorder": "total ascending"},
    xaxis_title="Share with access (%)",
    yaxis_title="",
    template="plotly_white",
    margin=dict(l=10, r=10, t=30, b=10)
)

fig_rank = add_regional_avg_line(fig_rank, rank_avg_pct)
st.plotly_chart(fig_rank, use_container_width=True)

st.divider()

# ----------------------------------------------------
# ACCESSIBILITY GAP
# ----------------------------------------------------
st.subheader("Accessibility gap")

gap_service = st.selectbox("Service", ["Hospital", "School"])

gap_df = df[[ISO_COL]].copy()

if gap_service == "Hospital":
    gap_thr = st.selectbox("Threshold", list(HOSP_GAP_OPTIONS.keys()))
    _, gap_share_col = HOSP_GAP_OPTIONS[gap_thr]
    gap_df["gap_share"] = pd.to_numeric(df.get(gap_share_col), errors="coerce")
else:
    gap_thr = st.selectbox("Threshold", list(SCHOOL_GAP_FROM_WITHIN.keys()))
    within = pd.to_numeric(df.get(SCHOOL_GAP_FROM_WITHIN[gap_thr]), errors="coerce")
    gap_df["gap_share"] = 1 - within

gap_df = gap_df.dropna(subset=["gap_share"]).sort_values("gap_share", ascending=False).copy()
gap_df["gap_pct"] = gap_df["gap_share"] * 100
gap_avg_pct = safe_mean(gap_df["gap_share"]) * 100 if len(gap_df) else np.nan

fig_gap = px.bar(
    gap_df,
    x="gap_pct",
    y=ISO_COL,
    orientation="h"
)

fig_gap.update_layout(
    height=plot_height_for_n(len(gap_df)),
    yaxis={"categoryorder": "total ascending"},
    xaxis_title="Population beyond threshold (%)",
    yaxis_title="",
    template="plotly_white",
    margin=dict(l=10, r=10, t=30, b=10)
)

fig_gap = add_regional_avg_line(fig_gap, gap_avg_pct)
st.plotly_chart(fig_gap, use_container_width=True)

st.divider()

# ----------------------------------------------------
# DEMOGRAPHIC INEQUALITY
# ----------------------------------------------------
st.subheader("Healthcare access inequality across population groups")

demo_group = st.selectbox("Population group", list(DEMOGRAPHIC_OPTIONS.keys()))

pop_col_demo, share_col_demo = DEMOGRAPHIC_OPTIONS[demo_group]

demo_df = df[[ISO_COL]].copy()
demo_df["gap_share"] = pd.to_numeric(df.get(share_col_demo), errors="coerce")
demo_df["gap_pop"] = pd.to_numeric(df.get(pop_col_demo), errors="coerce")

demo_df = demo_df.dropna(subset=["gap_share"]).sort_values("gap_share", ascending=False).copy()
demo_df["gap_pct"] = demo_df["gap_share"] * 100
demo_avg_pct = safe_mean(demo_df["gap_share"]) * 100 if len(demo_df) else np.nan

fig_demo = px.bar(
    demo_df,
    x="gap_pct",
    y=ISO_COL,
    orientation="h",
    title=f"{demo_group} living more than 60 minutes from a hospital"
)

fig_demo.update_layout(
    height=plot_height_for_n(len(demo_df)),
    yaxis={"categoryorder": "total ascending"},
    xaxis_title="Population group beyond 60 minutes (%)",
    yaxis_title="",
    template="plotly_white",
    margin=dict(l=10, r=10, t=50, b=10)
)

fig_demo = add_regional_avg_line(fig_demo, demo_avg_pct)
st.plotly_chart(fig_demo, use_container_width=True)

st.caption(
    "This chart highlights inequality in healthcare accessibility across demographic groups. "
    "Higher percentages indicate larger shares of vulnerable populations living far from hospitals."
)