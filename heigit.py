import os
import re
import time
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

import requests

# ==============================
# CONFIG
# ==============================
BASE_URL = "https://data.humdata.org/api/3/action"
ORG_SLUG = "heidelberg-institute-for-geoinformation-technology"
QUERY_TEXT = '"Accessibility Indicators"'
ROWS = 1000

OUT_BASE = Path(r"E:\HeiGIT")  # <-- target root folder
OUT_BASE.mkdir(parents=True, exist_ok=True)

WANTED_FORMATS = {"CSV", "GPKG"}  # download only these (format OR extension)
TIMEOUT = 90
RETRIES = 4
SLEEP_BETWEEN_DATASETS_SEC = 0.05
USER_AGENT = "HeiGIT-HDX-ATO-downloader/1.0 (local script)"

# If True, will create E:\HeiGIT\_logs and write run logs + inventories
WRITE_LOGS = True


# ==============================
# ATO ISO3 (from you)
# ==============================
ATO_ISO3 = [
    "AFG","ARM","AUS","AZE","BGD","BRN","BTN","CHN","COK","FJI","FSM","GEO","HKG","IDN","IND","IRN","JPN","KAZ","KGZ","KHM","KIR",
    "KOR","LAO","LKA","MDV","MHL","MMR","MNG","MYS","NIU","NPL","NRU","NZL","PAK","PHL","PLW","PNG","RUS","SGP","SLB","THA","TJK",
    "TKM","TLS","TON","TUR","TUV","TWN","UZB","VNM","VUT","WSM"
]

# ==============================
# ISO3 -> country_slug mapping
# (based on your observed slugs)
# ==============================
ISO3_TO_SLUG = {
    "AFG": "afghanistan",
    "ARM": "armenia",
    "AUS": "australia",
    "AZE": "azerbaijan",
    "BGD": "bangladesh",
    "BRN": "brunei",
    "BTN": "bhutan",
    "CHN": "china",
    "COK": "cook-islands",              # may or may not exist in inventory
    "FJI": "fiji",
    "FSM": "micronesia",
    "GEO": "georgia",
    "HKG": "hong-kong",                 # may or may not exist in inventory
    "IDN": "indonesia",
    "IND": "india",
    "IRN": "iran",
    "JPN": "japan",
    "KAZ": "kazakhstan",
    "KGZ": "kyrgyzstan",
    "KHM": "cambodia",
    "KIR": "kiribati",
    "KOR": "south-korea",
    "LAO": "laos",
    "LKA": "sri-lanka",
    "MDV": "maldives",
    "MHL": "marshall-islands",
    "MMR": "myanmar",
    "MNG": "mongolia",
    "MYS": "malaysia",
    "NIU": "niue",                      # may or may not exist in inventory
    "NPL": "nepal",
    "NRU": "nauru",
    "NZL": "new-zealand",
    "PAK": "pakistan",
    "PHL": "philippines",
    "PLW": "palau",
    "PNG": "papua-new-guinea",
    "RUS": "russia",
    "SGP": "singapore",
    "SLB": "solomon-islands",
    "THA": "thailand",
    "TJK": "tajikistan",
    "TKM": "turkmenistan",
    "TLS": "timor-leste",
    "TON": "tonga",
    "TUR": "turkey",
    "TUV": "tuvalu",
    "TWN": "taiwan",
    "UZB": "uzbekistan",
    "VNM": "vietnam",
    "VUT": "vanuatu",
    "WSM": "samoa",
}

# Reverse map
SLUG_TO_ISO3 = {v: k for k, v in ISO3_TO_SLUG.items() if k in ATO_ISO3}

# If dataset slugs have minor variations, normalize here
SLUG_ALIASES = {
    # Example: "lao-pdr": "laos",
    # Example: "korea-republic-of": "south-korea",
}


# ==============================
# Helpers
# ==============================
def safe_name(s: str, fallback: str = "file") -> str:
    s = (s or "").strip()
    if not s:
        s = fallback
    s = re.sub(r'[\\/:*?"<>|]+', "_", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:180]


def ext_from_url(url: str) -> str:
    base = url.split("?", 1)[0]
    return Path(base).suffix.lower()


def want_resource(fmt: str, url: str) -> bool:
    fmt_u = (fmt or "").strip().upper()
    ext_u = ext_from_url(url).lstrip(".").upper()
    return (fmt_u in WANTED_FORMATS) or (ext_u in WANTED_FORMATS)


def request_json(session: requests.Session, action: str, params: Optional[dict] = None) -> Dict[str, Any]:
    url = f"{BASE_URL}/{action}"
    last_err = None
    for attempt in range(1, RETRIES + 1):
        try:
            r = session.get(url, params=params, timeout=TIMEOUT)
            r.raise_for_status()
            data = r.json()
            if not data.get("success", False):
                raise RuntimeError(f"CKAN returned success=false for {action}: {data}")
            return data
        except Exception as e:
            last_err = e
            if attempt < RETRIES:
                time.sleep(1.5 * attempt)
            else:
                raise
    raise last_err  # unreachable


def stream_download(session: requests.Session, url: str, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    last_err = None
    for attempt in range(1, RETRIES + 1):
        try:
            with session.get(url, stream=True, timeout=TIMEOUT, allow_redirects=True) as r:
                r.raise_for_status()
                with open(out_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1024 * 256):
                        if chunk:
                            f.write(chunk)
            return
        except Exception as e:
            last_err = e
            # remove partial
            try:
                if out_path.exists():
                    out_path.unlink()
            except Exception:
                pass
            if attempt < RETRIES:
                time.sleep(2.0 * attempt)
            else:
                raise
    raise last_err  # unreachable


def extract_country_slug(dataset_slug: str) -> Optional[str]:
    """
    Dataset slug pattern: <country>-accessibility-indicators
    Returns <country> part.
    """
    slug = (dataset_slug or "").strip().lower()
    m = re.match(r"(.+)-accessibility-indicators$", slug)
    if not m:
        return None
    country = m.group(1)
    country = SLUG_ALIASES.get(country, country)
    return country


def log_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(text + "\n")


# ==============================
# Main
# ==============================
def main():
    logs_dir = OUT_BASE / "_logs"
    if WRITE_LOGS:
        logs_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    # 1) Search datasets (HeiGIT + phrase)
    search_params = {
        "q": QUERY_TEXT,
        "fq": f"organization:{ORG_SLUG}",
        "rows": ROWS,
    }
    print(f"Searching HDX: org={ORG_SLUG} q={QUERY_TEXT}")
    search = request_json(session, "package_search", params=search_params)
    datasets: List[Dict[str, Any]] = search["result"]["results"]
    print(f"Matched datasets (raw): {search['result']['count']} (retrieved {len(datasets)})")

    # 2) Build inventory and filter to ATO
    inventory_rows: List[Dict[str, Any]] = []
    ato_datasets: List[Tuple[str, str, str]] = []  # (dataset_id, dataset_slug, iso3)

    for ds in datasets:
        ds_id = ds.get("id")
        ds_slug = (ds.get("name") or "").strip().lower()
        title = ds.get("title")
        modified = ds.get("metadata_modified")

        cslug = extract_country_slug(ds_slug)
        iso3 = SLUG_TO_ISO3.get(cslug) if cslug else None

        inventory_rows.append({
            "dataset_id": ds_id,
            "dataset_slug": ds_slug,
            "title": title,
            "metadata_modified": modified,
            "country_slug": cslug,
            "ato_iso3": iso3,
            "is_ato": bool(iso3),
        })

        if iso3:
            ato_datasets.append((ds_id, ds_slug, iso3))

    # write inventory CSV
    try:
        import pandas as pd
        inv_df = pd.DataFrame(inventory_rows)
        inv_all_path = OUT_BASE / "heigit_accessibility_inventory_all.csv"
        inv_ato_path = OUT_BASE / "heigit_accessibility_inventory_ato.csv"
        inv_df.to_csv(inv_all_path, index=False, encoding="utf-8")
        inv_df[inv_df["is_ato"]].to_csv(inv_ato_path, index=False, encoding="utf-8")
        print(f"Saved inventory: {inv_all_path}")
        print(f"Saved ATO inventory: {inv_ato_path}")
    except Exception as e:
        print(f"WARNING: could not write inventory CSVs (pandas missing?): {e}")
        print("If you want inventories, install pandas: pip install pandas")

    # missing ATO iso3 check (ISO3 expected but not present in inventory)
    present_iso3 = set([iso3 for _, _, iso3 in ato_datasets])
    missing_iso3 = [iso3 for iso3 in ATO_ISO3 if iso3 not in present_iso3]
    if missing_iso3:
        msg = "ATO ISO3 missing from inventory (no matching dataset slug found): " + ", ".join(missing_iso3)
        print(msg)
        if WRITE_LOGS:
            log_write(logs_dir / "missing_ato_iso3.txt", msg)

    print(f"ATO datasets to download: {len(ato_datasets)}")

    # 3) Download resources (CSV + GPKG) for each ATO dataset
    downloaded = 0
    skipped = 0
    failed = 0

    for idx, (ds_id, ds_slug, iso3) in enumerate(ato_datasets, start=1):
        print(f"\n[{idx}/{len(ato_datasets)}] {iso3} :: {ds_slug}")

        try:
            pkg = request_json(session, "package_show", params={"id": ds_id})["result"]
        except Exception as e:
            failed += 1
            err = f"[FAIL package_show] {iso3} {ds_slug}: {e}"
            print(err)
            if WRITE_LOGS:
                log_write(logs_dir / "failures.txt", err)
            continue

        resources = pkg.get("resources", [])
        wanted = []
        for res in resources:
            url = (res.get("url") or "").strip()
            if not url:
                continue
            fmt = (res.get("format") or "").strip()
            if want_resource(fmt, url):
                wanted.append(res)

        if not wanted:
            print("  - no CSV/GPKG resources found; skipping.")
            time.sleep(SLEEP_BETWEEN_DATASETS_SEC)
            continue

        # Save package metadata (optional)
        if WRITE_LOGS:
            meta_path = OUT_BASE / iso3 / "_metadata"
            meta_path.mkdir(parents=True, exist_ok=True)
            try:
                import json
                with open(meta_path / f"{ds_slug}.package_show.json", "w", encoding="utf-8") as f:
                    json.dump(pkg, f, indent=2)
            except Exception:
                pass

        # Download each resource
        for res in wanted:
            url = res["url"].strip()
            fmt_u = (res.get("format") or "").strip().upper()
            ext = ext_from_url(url)
            if not ext:
                ext = "." + (fmt_u.lower() if fmt_u else "dat")

            base = safe_name(res.get("name") or res.get("title") or res.get("id") or "resource")
            # Put into subfolders by format for cleanliness
            fmt_folder = fmt_u if fmt_u else ext.lstrip(".").upper()
            out_dir = OUT_BASE / iso3 / fmt_folder
            out_path = out_dir / f"{base}{ext}"

            if out_path.exists() and out_path.stat().st_size > 0:
                skipped += 1
                continue

            print(f"  - downloading {fmt_folder}: {out_path.name}")
            try:
                stream_download(session, url, out_path)
                downloaded += 1
            except Exception as e:
                failed += 1
                err = f"[FAIL download] {iso3} {ds_slug} :: {out_path.name} <- {url} :: {e}"
                print("    " + err)
                if WRITE_LOGS:
                    log_write(logs_dir / "failures.txt", err)

        time.sleep(SLEEP_BETWEEN_DATASETS_SEC)

    print("\n==============================")
    print("DONE")
    print(f"Downloaded: {downloaded}")
    print(f"Skipped (exists): {skipped}")
    print(f"Failed: {failed}")
    print(f"Output: {OUT_BASE}")
    print("==============================\n")


if __name__ == "__main__":
    main()