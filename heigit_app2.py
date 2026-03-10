import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

# 1. Page Configuration
st.set_page_config(page_title="Asia-Pacific Service Delivery Monitor", layout="wide")


# 2. Data Loading & Cleaning
@st.cache_data
def load_data():
    # File Paths (Update these to your local paths)
    accessibility_file = 'heigit_access_indicators_ADM0_ALL.xlsx'
    economies_file = 'Economies.xlsx'

    # Reading specific sheets from Excel
    df_ind = pd.read_excel(accessibility_file, sheet_name='ADM0_indicators')
    df_cov = pd.read_excel(accessibility_file, sheet_name='coverage_check')
    df_econ = pd.read_excel(economies_file, sheet_name='Sheet1')

    # Merge Mapping
    mapping = df_econ[['economy', 'economy_ato_subgroup', 'economy_name']].rename(columns={'economy': 'country'})
    df = df_ind.merge(mapping, on='country', how='left')

    # Fill missing subgroups for robust plotting
    df['economy_ato_subgroup'] = df['economy_ato_subgroup'].fillna('Other/Unclassified')

    return df, df_cov


try:
    df, df_cov = load_data()
except Exception as e:
    st.error(f"Error loading Excel files: {e}. Please ensure file and sheet names match exactly.")
    st.stop()


# Helper for weighted calculations (MDB Standard: Never average shares directly)
def get_weighted_stat(data, num_col, den_col):
    return data[num_col].sum() / data[den_col].sum() if data[den_col].sum() > 0 else 0


# --- HEADER SECTION ---
st.title("🌏 Asia-Pacific Service Delivery Monitor")
st.markdown("#### *Strategic Accessibility Analysis for International Development*")
st.divider()

# --- SECTION 1: REGIONAL KPI RIBBON ---
st.header("1. Executive Summary: The Reach Gap")
k1, k2, k3, k4 = st.columns(4)

total_pop = df['hospital_total_pop_est'].sum()
reached_h = df['pop_60min_hospital_pop'].sum()
unreached_m = (total_pop - reached_h) / 1e6
reg_avg = reached_h / total_pop

k1.metric("Reg. Hospital Access (60m)", f"{reg_avg:.1%}")
k2.metric("Population Beyond 60m Hosp", f"{unreached_m:.1f}M", delta="High Risk", delta_color="inverse")
k3.metric("Reg. School Reach (10km)", f"{(df['pop_10km_school_pop'].sum() / df['edu_total_pop_est'].sum()):.1%}")
k4.metric("Countries Monitored", len(df))

# --- SECTION 2: GEOSPATIAL REACH MAP ---
st.header("2. Geospatial Distribution of Services")
map_view = st.radio("Toggle View:", ["Healthcare (60m Travel Time)", "Education (10km Distance)"], horizontal=True)
map_col = 'pop_60min_hospital_share' if "Health" in map_view else 'pop_10km_school_share'

fig_map = px.choropleth(df, locations="country", color=map_col,
                        hover_name="economy_name", color_continuous_scale="YlGnBu",
                        projection="natural earth", title=f"Regional {map_view} Heatmap")
fig_map.update_layout(margin={"r": 0, "t": 40, "l": 0, "b": 0}, height=500)
st.plotly_chart(fig_map, use_container_width=True)

# --- SECTION 3: ATO SUB-REGION BENCHMARKING ---
st.header("3. Sub-Regional Benchmarking")
selected_group = st.selectbox("Select ATO Subgroup for Comparison:", sorted(df['economy_ato_subgroup'].unique()))

sub_df = df[df['economy_ato_subgroup'] == selected_group].sort_values(map_col)
group_avg = get_weighted_stat(sub_df,
                              'pop_60min_hospital_pop' if "Health" in map_view else 'pop_10km_school_pop',
                              'hospital_total_pop_est' if "Health" in map_view else 'edu_total_pop_est')

fig_bench = px.bar(sub_df, x=map_col, y='economy_name', orientation='h',
                   color=map_col, color_continuous_scale="Blues",
                   title=f"Peer Comparison: {selected_group}")
fig_bench.add_vline(x=group_avg, line_dash="dash", line_color="red",
                    annotation_text=f"Sub-regional Avg: {group_avg:.1%}")
st.plotly_chart(fig_bench, use_container_width=True)

# --- SECTION 4: EQUITY & VULNERABILITY MATRIX ---
st.header("4. Infrastructure Equity Analysis")
st.markdown(
    "The **Equity Quadrant** identifies where vulnerable groups (Children Under 5) face higher barriers than the general population.")

# Robust cleaning for bubble chart sizing
plot_df = df.dropna(
    subset=['hospital_total_pop_est', 'pop_gap_60min_hospital_share', 'under5_gap_60min_hospital_share'])
plot_df['hospital_total_pop_est'] = plot_df['hospital_total_pop_est'].clip(lower=0)

fig_equity = px.scatter(plot_df, x='pop_gap_60min_hospital_share', y='under5_gap_60min_hospital_share',
                        size='hospital_total_pop_est', hover_name='economy_name', color='economy_ato_subgroup',
                        labels={'pop_gap_60min_hospital_share': 'General Pop Gap (%)',
                                'under5_gap_60min_hospital_share': 'Children Under-5 Gap (%)'},
                        size_max=45)

# 45-degree parity line: Above the line means children are more isolated than the average.
max_val = max(plot_df['pop_gap_60min_hospital_share'].max(), plot_df['under5_gap_60min_hospital_share'].max())
fig_equity.add_shape(type="line", x0=0, y0=0, x1=max_val, y1=max_val,
                     line=dict(color="grey", dash="dot"))
st.plotly_chart(fig_equity, use_container_width=True)

# --- SECTION 5: DATA MATURITY & OSM COVERAGE ---
st.divider()
st.subheader("5. Monitoring Credibility: Map Coverage vs. Reported Access")
merged_cov = df.merge(df_cov, on='country')
fig_cov = px.scatter(merged_cov, x='hospital_max_share_at_max_range', y='pop_60min_hospital_share',
                     hover_name='economy_name', trendline="ols",
                     title="Infrastructure Maturity vs. OSM Mapping Completeness",
                     labels={'hospital_max_share_at_max_range': 'Map Completeness (OSM)',
                             'pop_60min_hospital_share': 'Reported Access (60m)'})
st.plotly_chart(fig_cov, use_container_width=True)

st.markdown("---")
st.caption(
    "Standard Disclaimer: Analysis based on HeiGIT indicators and ATO Economy mapping. All totals are population-weighted.")