# heigit_dashboard.py
# One-tab professional dashboard with demographic inequality analysis
# Updated with:
# - Regional average benchmark on all plots
# - Remote high-resolution country boundaries from GitHub
# - MapLibre basemap using supplied style JSON
# - Auto-zoom to selected region
# - Professional floating continuous colorbar legend inside map
#
# Run:
#   streamlit run heigit_dashboard.py
#
# Files expected in same directory:
#   - heigit_access_indicators_ADM0_ALL.xlsx
#   - Economies.xlsx
#   - map_atlas_style_open.json   (optional; if missing, script falls back to STYLE_URL)

import os
import copy
import json
import requests
import pandas as pd
import numpy as np
import streamlit as st
import streamlit.components.v1 as components
import plotly.express as px

st.set_page_config(page_title="Asia-Pacific Access Dashboard", layout="wide")

# ----------------------------------------------------
# FILES
# ----------------------------------------------------
DATA_FILE = "heigit_access_indicators_ADM0_ALL.xlsx"
ECON_FILE = "Economies.xlsx"
STYLE_FILE = "map_atlas_style_open.json"
STYLE_URL = "https://asiantransportobservatory.org/static/front/map_atlas_style_open.json"

# Remote high-resolution boundaries (no local download needed)
BOUNDARY_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
    "master/geojson/ne_50m_admin_0_countries.geojson"
)

ISO_COL = "country"
REGION_COL = "economy_ato_subgroup"
ECON_ISO_COL = "economy"

MAP_HEIGHT = 620
DEFAULT_CENTER = {"lat": 15, "lon": 105, "zoom": 2.2}

EST_ECONOMIES = {
    "AFG", "BGD", "BTN", "BRN", "KHM", "IDN", "IND", "IRN", "JPN", "LAO",
    "MYS", "MDV", "MNG", "MMR", "NPL", "PHL", "RUS", "SGP", "LKA", "THA", "VNM"
}
EST_REGION_LABEL = "EST Economies"

# ----------------------------------------------------
# INDICATOR OPTIONS
# ----------------------------------------------------
HOSP_OPTIONS = {
    "30 min": ("pop_30min_hospital_pop", "pop_30min_hospital_share"),
    "60 min": ("pop_60min_hospital_pop", "pop_60min_hospital_share"),
    "90 min": ("pop_90min_hospital_pop", "pop_90min_hospital_share"),
    "110 min": ("pop_110min_hospital_pop", "pop_110min_hospital_share"),
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
    ">110 min": ("pop_>120min_hospital_pop", "pop_>120min_hospital_share"),
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


def rgba_string(rgba):
    r, g, b, a = rgba
    return f"rgba({r},{g},{b},{a / 255:.3f})"


def color_scale_viridis(v):
    if pd.isna(v):
        return [160, 160, 160, 70]

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
            return rgb + [185]

    return [160, 160, 160, 70]


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


@st.cache_data(show_spinner=False)
def load_map_style(style_file, style_url):
    if os.path.exists(style_file):
        with open(style_file, "r", encoding="utf-8") as f:
            return json.load(f)

    r = requests.get(style_url, timeout=60)
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
        fill_rgba = color_scale_viridis(value)

        props["country_code"] = iso or ""
        props["country_name"] = (label_map.get(iso, iso) if label_map else iso) or ""
        props["value"] = None if pd.isna(value) else float(value)
        props["value_pct"] = None if pd.isna(value) else round(float(value) * 100, 1)
        props["fill_color"] = fill_rgba
        props["fill_color_css"] = rgba_string(fill_rgba)
        props["has_value"] = bool(not pd.isna(value))

        feat["properties"] = props
    return geojson


def get_region_geojson(geojson, iso_set):
    features = []
    for feat in geojson.get("features", []):
        iso = get_feature_iso(feat.get("properties", {}))
        if iso in iso_set:
            features.append(feat)
    return {"type": "FeatureCollection", "features": features}


def compute_feature_centroid(geom):
    coords = extract_coords_from_geometry(geom)
    if not coords:
        return None, None
    xs = [x for x, y in coords if -180 <= x <= 180 and -90 <= y <= 90]
    ys = [y for x, y in coords if -180 <= x <= 180 and -90 <= y <= 90]
    if not xs or not ys:
        return None, None
    return float(sum(xs) / len(xs)), float(sum(ys) / len(ys))


def extract_bubble_points(geojson_data):
    rows = []
    for feat in geojson_data.get("features", []):
        props = feat.get("properties", {})
        iso = props.get("country_code") or get_feature_iso(props)
        value = props.get("value")
        value_pct = props.get("value_pct")
        if not iso or value is None or value_pct is None:
            continue

        lon, lat = compute_feature_centroid(feat.get("geometry", {}))
        if lon is None or lat is None:
            continue

        rows.append({
            "country_code": iso,
            "country_name": props.get("country_name") or iso,
            "value": float(value),
            "value_pct": float(value_pct),
            "longitude": lon,
            "latitude": lat,
        })
    return pd.DataFrame(rows)


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
        return {
            "latitude": default_lat,
            "longitude": default_lon,
            "zoom": default_zoom,
            "pitch": 0,
            "bearing": 0,
        }

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

    return {
        "latitude": center_lat,
        "longitude": center_lon,
        "zoom": zoom,
        "pitch": 0,
        "bearing": 0,
    }


def render_maplibre_map(style_url, style_dict, geojson_data, view_state, legend_min, legend_max, height=620):
    records = []
    data_features = []

    for feat in geojson_data.get("features", []):
        props = feat.get("properties", {})
        iso = props.get("country_code") or get_feature_iso(props)
        if not iso:
            continue

        value = props.get("value")
        value_pct = props.get("value_pct")
        if value is None or value_pct is None:
            continue

        records.append(
            {
                "country_code": iso,
                "country_name": props.get("country_name") or iso,
                "value": float(value),
                "value_pct": float(value_pct),
            }
        )
        data_features.append(feat)

    map_df = pd.DataFrame(records)
    if map_df.empty:
        st.info("No map data available for the current filters.")
        return

    data_geojson = {"type": "FeatureCollection", "features": data_features}

    colorscale = [
        [0.00, "#440154"],
        [0.25, "#3b528b"],
        [0.50, "#21918c"],
        [0.75, "#5ec962"],
        [1.00, "#fde725"],
    ]

    fig = px.choropleth(
        map_df,
        geojson=data_geojson,
        locations="country_code",
        featureidkey="properties.country_code",
        color="value_pct",
        custom_data=["country_name", "country_code", "value_pct"],
        color_continuous_scale=colorscale,
        range_color=(legend_min, legend_max),
    )

    fig.update_traces(
        marker_line_color="rgba(255,255,255,0.40)",
        marker_line_width=0.5,
        hovertemplate=(
            "<b>%{customdata[0]}</b><br>" +
            "ISO3: %{customdata[1]}<br>" +
            "Share with access: %{customdata[2]:.1f}%<extra></extra>"
        ),
        selector=dict(type="choropleth"),
    )

    fig.update_geos(
        visible=False,
        showcountries=False,
        showcoastlines=True,
        coastlinecolor="rgba(20,20,20,0.28)",
        coastlinewidth=0.6,
        showland=True,
        landcolor="rgb(248,248,246)",
        showocean=True,
        oceancolor="rgb(235,242,248)",
        showframe=False,
        fitbounds="locations",
        projection_type="natural earth",
        center={"lat": view_state.get("latitude", 15), "lon": view_state.get("longitude", 105)},
    )

    fig.update_layout(
        height=height,
        margin=dict(l=0, r=0, t=0, b=0),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        coloraxis_colorbar=dict(
            title="Share with access (%)",
            thickness=18,
            len=0.28,
            x=0.985,
            xanchor="right",
            y=0.5,
            yanchor="middle",
            bgcolor="rgba(255,255,255,0.96)",
            outlinecolor="#d0d0d0",
            outlinewidth=1,
            tickformat=".1f",
        ),
    )

    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def render_bubble_map(geojson_data, view_state, legend_min, legend_max, height=620):
    bubble_df = extract_bubble_points(geojson_data)
    if bubble_df.empty:
        st.info("No map data available for the current filters.")
        return

    colorscale = [
        [0.00, "#440154"],
        [0.25, "#3b528b"],
        [0.50, "#21918c"],
        [0.75, "#5ec962"],
        [1.00, "#fde725"],
    ]

    fig = px.scatter_geo(
        bubble_df,
        lat="latitude",
        lon="longitude",
        size="value_pct",
        color="value_pct",
        hover_name="country_name",
        hover_data={"country_code": True, "value_pct": ':.1f', "latitude": False, "longitude": False},
        color_continuous_scale=colorscale,
        range_color=(legend_min, legend_max),
        size_max=34,
    )

    fig.update_traces(
        marker=dict(line=dict(color="rgba(255,255,255,0.75)", width=0.8), opacity=0.85),
        hovertemplate=(
            "<b>%{hovertext}</b><br>" +
            "ISO3: %{customdata[0]}<br>" +
            "Share with access: %{marker.color:.1f}%<extra></extra>"
        )
    )

    fig.update_geos(
        visible=False,
        showcountries=False,
        showcoastlines=True,
        coastlinecolor="rgba(20,20,20,0.28)",
        coastlinewidth=0.6,
        showland=True,
        landcolor="rgb(248,248,246)",
        showocean=True,
        oceancolor="rgb(235,242,248)",
        showframe=False,
        fitbounds="locations",
        projection_type="natural earth",
        center={"lat": view_state.get("latitude", 15), "lon": view_state.get("longitude", 105)},
    )

    fig.update_layout(
        height=height,
        margin=dict(l=0, r=0, t=0, b=0),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        coloraxis_colorbar=dict(
            title="Share with access (%)",
            thickness=18,
            len=0.28,
            x=0.985,
            xanchor="right",
            y=0.5,
            yanchor="middle",
            bgcolor="rgba(255,255,255,0.96)",
            outlinecolor="#d0d0d0",
            outlinewidth=1,
            tickformat=".1f",
        ),
    )

    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


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
map_style = load_map_style(STYLE_FILE, STYLE_URL)

df_all = df_all.merge(
    econ.rename(columns={ECON_ISO_COL: ISO_COL}),
    on=ISO_COL,
    how="left"
)
df_all[REGION_COL] = df_all[REGION_COL].fillna("Unknown")
df_all[ISO_COL] = df_all[ISO_COL].astype(str).str.upper().str.strip()

region_options = ["All", EST_REGION_LABEL] + sorted(df_all[REGION_COL].dropna().unique())

# ----------------------------------------------------
# HEADER
# ----------------------------------------------------
st.title("Access to Essential Services in Asia-Pacific")

st.caption(
    "Dashboard summarizing accessibility to hospitals and schools, "
    "including geographic distribution, rankings, regional comparisons, "
    "accessibility gaps, and demographic inequalities. Compiled from HeiGIT Accessibility Indicators (https://giscience.github.io/open-access-lens/)"
)

# ----------------------------------------------------
# FILTERS
# ----------------------------------------------------
c1, c2, c3, c4 = st.columns([1.2, 1.2, 1.2, 1.4])

with c1:
    region = st.selectbox(
        "ATO subregion",
        region_options,
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
    map_view = st.radio(
        "Map view",
        ["Choropleth", "Bubble map"],
        horizontal=True
    )
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
if region == EST_REGION_LABEL:
    df = df[df[ISO_COL].isin(EST_ECONOMIES)].copy()
elif region != "All":
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
    else {
        "latitude": DEFAULT_CENTER["lat"],
        "longitude": DEFAULT_CENTER["lon"],
        "zoom": DEFAULT_CENTER["zoom"],
        "pitch": 0,
        "bearing": 0,
    }
)

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

if map_view == "Bubble map":
    render_bubble_map(
        geojson_data=geojson_for_map,
        view_state=view_state,
        legend_min=legend_min,
        legend_max=legend_max,
        height=MAP_HEIGHT,
    )
else:
    render_maplibre_map(
        style_url=STYLE_URL,
        style_dict=map_style,
        geojson_data=geojson_for_map,
        view_state=view_state,
        legend_min=legend_min,
        legend_max=legend_max,
        height=MAP_HEIGHT,
    )

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