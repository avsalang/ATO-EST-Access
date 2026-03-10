import os
import re
import pandas as pd
import numpy as np

BASE_DIR = r"E:\HeiGIT\CSV"
OUT_XLSX = os.path.join(BASE_DIR, "heigit_access_indicators_ADM0_ALL.xlsx")
ADMIN_LEVEL = "ADM0"

# ============================================================
# Constants for stable outputs (even when datasets are missing)
# ============================================================
TIME_THRESHOLDS = [(30, 1800), (60, 3600), (90, 5400), (120, 7200)]
EDU_THRESHOLDS  = [(5, 5000), (10, 10000), (20, 20000), (50, 50000)]

# -------- Helpers --------
def pct_to_frac(x):
    if pd.isna(x):
        return np.nan
    try:
        return float(x) / 100.0
    except Exception:
        return np.nan

def get_row(df, pop_type, rng):
    sub = df[(df["population_type"] == pop_type) & (df["range"] == rng)]
    return None if sub.empty else sub.iloc[0]

def get_pop_share(df, pop_type, rng):
    row = get_row(df, pop_type, rng)
    if row is None:
        return (np.nan, np.nan)
    return float(row["population"]), pct_to_frac(row["population_share"])

def estimate_total_from_last(df, pop_type):
    if df is None or df.empty:
        return np.nan
    if "range" not in df.columns:
        return np.nan
    last_rng = float(df["range"].max())
    row = get_row(df, pop_type, last_rng)
    if row is None:
        return np.nan
    pop_last = float(row["population"])
    share_last = pct_to_frac(row["population_share"])
    if share_last <= 0 or np.isnan(share_last):
        return np.nan
    return pop_last / share_last

def percentile_time_seconds(df, pop_type, p):
    s = df[df["population_type"] == pop_type].sort_values("range").copy()
    if s.empty:
        return (np.nan, True)
    s["share_frac"] = s["population_share"].apply(pct_to_frac)
    if float(s["share_frac"].max()) < p:
        return (np.nan, True)
    return (float(s.loc[s["share_frac"] >= p, "range"].iloc[0]), False)

def avg_time_minutes_capped(df, pop_type, cap_seconds):
    s = df[df["population_type"] == pop_type].sort_values("range").copy()
    if s.empty or "population_interval_share" not in s.columns:
        return np.nan

    s["interval_share_frac"] = s["population_interval_share"].apply(pct_to_frac)
    prev = 0.0
    mids = []
    for r in s["range"].astype(float).tolist():
        mids.append((prev + r) / 2.0)
        prev = r
    s["mid_seconds"] = mids

    reachable_share = float(s["interval_share_frac"].sum())
    remainder = max(0.0, 1.0 - reachable_share)
    exp_seconds = float((s["mid_seconds"] * s["interval_share_frac"]).sum() + cap_seconds * remainder)
    return exp_seconds / 60.0

# -------- Missing-dataset safe outputs --------
def _nan_dict(keys):
    return {k: np.nan for k in keys}

def _time_service_keys(service_name):
    keys = [f"{service_name}_total_pop_est"]
    for mins, _ in TIME_THRESHOLDS:
        keys += [
            f"pop_{mins}min_{service_name}_pop",
            f"pop_{mins}min_{service_name}_share",
            f"pop_gap_{mins}min_{service_name}_pop",
            f"pop_gap_{mins}min_{service_name}_share",
        ]
    keys += [
        f"pop_beyond_60min_{service_name}_pop",
        f"pop_beyond_60min_{service_name}_share",
        f"median_{service_name}_travel_time_min",
        f"p90_{service_name}_travel_time_min",
        f"p90_{service_name}_travel_time_censored",
        f"avg_{service_name}_travel_time_min_capped_120",
        f"pop_>90min_{service_name}_pop",
        f"pop_>90min_{service_name}_share",
        f"pop_>120min_{service_name}_pop",
        f"pop_>120min_{service_name}_share",
    ]
    for prefix in ["under5", "women_childbearing", "elderly"]:
        keys += [
            f"{prefix}_gap_60min_{service_name}_pop",
            f"{prefix}_gap_60min_{service_name}_share",
        ]
    return keys

def _edu_keys():
    keys = ["edu_total_pop_est"]
    for km, _ in EDU_THRESHOLDS:
        keys += [
            f"pop_{km}km_school_pop",
            f"pop_{km}km_school_share",
            f"pop_gap_{km}km_school_pop",
            f"pop_gap_{km}km_school_share",
        ]
    keys += [
        "pop_>20km_school_pop",
        "pop_>20km_school_share",
        "pop_>50km_school_pop",
        "pop_>50km_school_share",
        "school_age_gap_10km_school_pop",
        "school_age_gap_10km_school_share",
    ]
    return keys

def compute_time_service_indicators(df, service_name, admin_level="ADM0"):
    # Skip (return NaNs) if dataset absent or schema incomplete
    required = {"admin_level", "population_type", "range", "population", "population_share"}
    if df is None or df.empty or not required.issubset(set(df.columns)):
        out = _nan_dict(_time_service_keys(service_name))
        out[f"p90_{service_name}_travel_time_censored"] = True
        return out

    d = df[df["admin_level"] == admin_level].copy()
    if d.empty:
        out = _nan_dict(_time_service_keys(service_name))
        out[f"p90_{service_name}_travel_time_censored"] = True
        return out

    out = {}
    total_pop_est = estimate_total_from_last(d, "total")
    out[f"{service_name}_total_pop_est"] = total_pop_est

    for mins, rng in TIME_THRESHOLDS:
        pop, share = get_pop_share(d, "total", rng)
        out[f"pop_{mins}min_{service_name}_pop"] = pop
        out[f"pop_{mins}min_{service_name}_share"] = share

    for mins, rng in TIME_THRESHOLDS:
        cov_pop, cov_share = get_pop_share(d, "total", rng)
        if not np.isnan(total_pop_est):
            out[f"pop_gap_{mins}min_{service_name}_pop"] = total_pop_est - cov_pop
            out[f"pop_gap_{mins}min_{service_name}_share"] = 1.0 - cov_share if not np.isnan(cov_share) else np.nan
        else:
            out[f"pop_gap_{mins}min_{service_name}_pop"] = np.nan
            out[f"pop_gap_{mins}min_{service_name}_share"] = np.nan

    if not np.isnan(total_pop_est):
        cov60_pop, cov60_share = get_pop_share(d, "total", 3600)
        out[f"pop_beyond_60min_{service_name}_pop"] = total_pop_est - cov60_pop
        out[f"pop_beyond_60min_{service_name}_share"] = 1.0 - cov60_share if not np.isnan(cov60_share) else np.nan
    else:
        out[f"pop_beyond_60min_{service_name}_pop"] = np.nan
        out[f"pop_beyond_60min_{service_name}_share"] = np.nan

    med_sec, _ = percentile_time_seconds(d, "total", 0.5)
    p90_sec, p90_cens = percentile_time_seconds(d, "total", 0.9)

    out[f"median_{service_name}_travel_time_min"] = med_sec / 60.0 if not np.isnan(med_sec) else np.nan
    out[f"p90_{service_name}_travel_time_min"] = p90_sec / 60.0 if not np.isnan(p90_sec) else np.nan
    out[f"p90_{service_name}_travel_time_censored"] = bool(p90_cens)

    out[f"avg_{service_name}_travel_time_min_capped_120"] = avg_time_minutes_capped(d, "total", 7200.0)

    if not np.isnan(total_pop_est):
        pop90, _ = get_pop_share(d, "total", 5400)
        pop120, _ = get_pop_share(d, "total", 7200)
        out[f"pop_>90min_{service_name}_pop"] = total_pop_est - pop90
        out[f"pop_>90min_{service_name}_share"] = (total_pop_est - pop90) / total_pop_est if not np.isnan(pop90) else np.nan
        out[f"pop_>120min_{service_name}_pop"] = total_pop_est - pop120
        out[f"pop_>120min_{service_name}_share"] = (total_pop_est - pop120) / total_pop_est if not np.isnan(pop120) else np.nan
    else:
        out[f"pop_>90min_{service_name}_pop"] = np.nan
        out[f"pop_>90min_{service_name}_share"] = np.nan
        out[f"pop_>120min_{service_name}_pop"] = np.nan
        out[f"pop_>120min_{service_name}_share"] = np.nan

    for poptype, prefix in [("under_5", "under5"), ("women_childbearing", "women_childbearing"), ("elderly", "elderly")]:
        tot = estimate_total_from_last(d, poptype)
        cov_pop, cov_share = get_pop_share(d, poptype, 3600)
        if not np.isnan(tot):
            out[f"{prefix}_gap_60min_{service_name}_pop"] = tot - cov_pop
            out[f"{prefix}_gap_60min_{service_name}_share"] = 1.0 - cov_share if not np.isnan(cov_share) else np.nan
        else:
            out[f"{prefix}_gap_60min_{service_name}_pop"] = np.nan
            out[f"{prefix}_gap_60min_{service_name}_share"] = np.nan

    # Ensure all keys exist (in case of edits above)
    for k in _time_service_keys(service_name):
        out.setdefault(k, np.nan)

    return out

def compute_education_indicators(df, admin_level="ADM0"):
    required = {"admin_level", "population_type", "range", "population", "population_share"}
    if df is None or df.empty or not required.issubset(set(df.columns)):
        return _nan_dict(_edu_keys())

    d = df[df["admin_level"] == admin_level].copy()
    if d.empty:
        return _nan_dict(_edu_keys())

    out = {}
    edu_total = estimate_total_from_last(d, "total")
    out["edu_total_pop_est"] = edu_total

    for km, rng in EDU_THRESHOLDS:
        pop, share = get_pop_share(d, "total", rng)
        out[f"pop_{km}km_school_pop"] = pop
        out[f"pop_{km}km_school_share"] = share
        if not np.isnan(edu_total):
            out[f"pop_gap_{km}km_school_pop"] = edu_total - pop
            out[f"pop_gap_{km}km_school_share"] = 1.0 - share if not np.isnan(share) else np.nan
        else:
            out[f"pop_gap_{km}km_school_pop"] = np.nan
            out[f"pop_gap_{km}km_school_share"] = np.nan

    if not np.isnan(edu_total):
        pop20, _ = get_pop_share(d, "total", 20000)
        pop50, _ = get_pop_share(d, "total", 50000)
        out["pop_>20km_school_pop"] = edu_total - pop20
        out["pop_>20km_school_share"] = (edu_total - pop20) / edu_total if not np.isnan(pop20) else np.nan
        out["pop_>50km_school_pop"] = edu_total - pop50
        out["pop_>50km_school_share"] = (edu_total - pop50) / edu_total if not np.isnan(pop50) else np.nan
    else:
        out["pop_>20km_school_pop"] = np.nan
        out["pop_>20km_school_share"] = np.nan
        out["pop_>50km_school_pop"] = np.nan
        out["pop_>50km_school_share"] = np.nan

    tot_sa = estimate_total_from_last(d, "school_age")
    cov_sa_pop, cov_sa_share = get_pop_share(d, "school_age", 10000)
    if not np.isnan(tot_sa):
        out["school_age_gap_10km_school_pop"] = tot_sa - cov_sa_pop
        out["school_age_gap_10km_school_share"] = 1.0 - cov_sa_share if not np.isnan(cov_sa_share) else np.nan
    else:
        out["school_age_gap_10km_school_pop"] = np.nan
        out["school_age_gap_10km_school_share"] = np.nan

    for k in _edu_keys():
        out.setdefault(k, np.nan)

    return out

# -------- Robust file discovery (case-insensitive, supports .csv.csv) --------
def discover_files(base_dir):
    if not os.path.isdir(base_dir):
        raise FileNotFoundError(f"BASE_DIR not found: {base_dir}")

    all_files = [f for f in os.listdir(base_dir) if os.path.isfile(os.path.join(base_dir, f))]
    lower_map = {f.lower(): f for f in all_files}

    def match_suffix(suffix):
        hits = []
        suf1 = suffix.lower()
        suf2 = (suffix + ".csv").lower()  # handles .csv.csv case
        for low, orig in lower_map.items():
            if low.endswith(suf1) or low.endswith(suf2):
                hits.append(orig)
        return sorted(hits)

    hosp_files = match_suffix("_hospitals_access_long.csv")
    phc_files  = match_suffix("_primary_healthcare_access_long.csv")
    edu_files  = match_suffix("_education_access_long.csv")

    iso_re_local = re.compile(r"^([a-z]{3})_", re.IGNORECASE)

    def to_map(file_list):
        m = {}
        for name in file_list:
            mo = iso_re_local.match(name)
            if not mo:
                continue
            iso = mo.group(1).upper()
            m[iso] = os.path.join(base_dir, name)
        return m

    return to_map(hosp_files), to_map(phc_files), to_map(edu_files), hosp_files, phc_files, edu_files

hosp_map, phc_map, edu_map, hosp_list, phc_list, edu_list = discover_files(BASE_DIR)

print("BASE_DIR:", BASE_DIR)
print("Found hospitals long:", len(hosp_list), "example:", hosp_list[:3])
print("Found PHC long:", len(phc_list), "example:", phc_list[:3])
print("Found education long:", len(edu_list), "example:", edu_list[:3])

all_isos = sorted(set(hosp_map) | set(phc_map) | set(edu_map))
if not all_isos:
    raise RuntimeError(
        "No country files discovered. Check BASE_DIR and filename suffixes.\n"
        f"BASE_DIR={BASE_DIR}\n"
        "Expected suffixes: _hospitals_access_long.csv, _primary_healthcare_access_long.csv, _education_access_long.csv"
    )

rows = []
missing = []
coverage = []

def max_share_at_max_range(df):
    if df is None or df.empty or "admin_level" not in df.columns:
        return np.nan
    d = df[df["admin_level"] == ADMIN_LEVEL].copy()
    if d.empty:
        return np.nan
    if "population_type" not in d.columns or "range" not in d.columns or "population_share" not in d.columns:
        return np.nan
    d = d[d["population_type"] == "total"].sort_values("range")
    if d.empty:
        return np.nan
    return pct_to_frac(d["population_share"].iloc[-1])

for iso in all_isos:
    has_h = iso in hosp_map
    has_p = iso in phc_map
    has_e = iso in edu_map

    missing.append({
        "country": iso,
        "has_hospitals": has_h,
        "has_primary_healthcare": has_p,
        "has_education": has_e,
        "hospitals_file": hosp_map.get(iso, ""),
        "primary_healthcare_file": phc_map.get(iso, ""),
        "education_file": edu_map.get(iso, ""),
    })

    hosp_df = pd.read_csv(hosp_map[iso], encoding="utf-8-sig") if has_h else pd.DataFrame()
    phc_df  = pd.read_csv(phc_map[iso],  encoding="utf-8-sig") if has_p else pd.DataFrame()
    edu_df  = pd.read_csv(edu_map[iso],  encoding="utf-8-sig") if has_e else pd.DataFrame()

    row = {"country": iso, "admin_level": ADMIN_LEVEL}

    # These now safely return all-NaN indicator dicts if the dataset is missing
    row.update(compute_time_service_indicators(hosp_df, "hospital", ADMIN_LEVEL))
    row.update(compute_time_service_indicators(phc_df, "primary_healthcare", ADMIN_LEVEL))
    row.update(compute_education_indicators(edu_df, ADMIN_LEVEL))

    rows.append(row)

    coverage.append({
        "country": iso,
        "hospital_max_share_at_max_range": max_share_at_max_range(hosp_df),
        "phc_max_share_at_max_range": max_share_at_max_range(phc_df),
        "education_max_share_at_max_range": max_share_at_max_range(edu_df),
    })

df_out = pd.DataFrame(rows)
df_missing = pd.DataFrame(missing)
df_cov = pd.DataFrame(coverage)

with pd.ExcelWriter(OUT_XLSX, engine="openpyxl") as writer:
    df_out.to_excel(writer, sheet_name="ADM0_indicators", index=False)
    df_cov.to_excel(writer, sheet_name="coverage_check", index=False)
    df_missing.to_excel(writer, sheet_name="missing_files", index=False)

print("Wrote:", OUT_XLSX)
print("Countries:", len(df_out))
print("Columns:", df_out.shape[1])