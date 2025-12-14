import os
import re
import glob
import unicodedata
import difflib
from typing import Dict, List, Optional, Tuple
from statistics import median

import geopandas as gpd
import pandas as pd
from shapely.geometry import box, Polygon, MultiPolygon

BASE = os.path.dirname(os.path.abspath(__file__))
QUERY_PATH = os.path.join(BASE, "query.csv")
SHAPE_PATH = os.path.join(BASE, "ne_10m_admin_1_states_provinces.shp")
OUT_DIR = os.path.join(BASE, "opengs_export")
OUT_PATH = os.path.join(OUT_DIR, "Population.csv")

EUROPE_COUNTRIES = [
    "ISL", "IRL", "GBR", "PRT", "ESP", "FRA", "AND", "BEL", "NLD", "LUX",
    "DEU", "CHE", "AUT", "LIE", "ITA", "SMR", "MLT", "DNK", "NOR", "SWE",
    "FIN", "EST", "LVA", "LTU", "POL", "CZE", "SVK", "HUN", "SVN", "HRV",
    "BIH", "SRB", "MNE", "MKD", "ALB", "KOS", "GRC", "CYP", "BGR", "ROU",
    "MDA", "UKR", "BLR", "RUS", "ARM", "GEO", "AZE", "TUR"
]

MIN_AREA_ABS = 1_000_000_000
STOPWORDS = {
    "province", "region", "county", "state", "district", "republic",
    "oblast", "voivodeship", "governorate", "gouvernorate", "prefecture",
    "department", "autonomous", "federal", "territory", "municipality"
}


def normalize(text: str) -> str:
    if not isinstance(text, str):
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"[`'\"]", "", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    words = [w for w in text.split() if w not in STOPWORDS]
    return " ".join(words).strip()


def normalize_iso(val: Optional[str]) -> str:
    if not isinstance(val, str):
        return ""
    return val.strip().upper().replace(" ", "")


def remove_holes(g):
    if g.geom_type == "Polygon":
        return Polygon(g.exterior)
    if g.geom_type == "MultiPolygon":
        return MultiPolygon([Polygon(p.exterior) for p in g.geoms])
    return g


def merge_small_absolute(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    gdf = gdf.copy()
    gdf["area"] = gdf.geometry.area
    merged = []

    for country, group in gdf.groupby("country"):
        group = group.copy()

        while True:
            small = group[group["area"] < MIN_AREA_ABS]
            if small.empty:
                break

            idx = small.index[0]
            target = group.loc[idx]

            candidates = group.drop(idx)
            if candidates.empty:
                group = group.drop(idx)
                continue

            nearest_idx = candidates.distance(target.geometry).sort_values().index[0]
            merged_geom = target.geometry.union(group.loc[nearest_idx].geometry)

            group.loc[nearest_idx, "geometry"] = merged_geom
            group = group.drop(idx)
            group["area"] = group.geometry.area

        merged.append(group)

    merged = pd.concat(merged, ignore_index=True)
    return merged.drop(columns="area")


def load_land() -> gpd.GeoDataFrame:
    admin = gpd.read_file(SHAPE_PATH)
    admin = admin.to_crs(3035)
    admin["geometry"] = admin.geometry.buffer(0)

    admin["country"] = admin["adm0_a3"]
    admin = admin[admin["country"].isin(EUROPE_COUNTRIES)].reset_index(drop=True)

    def cut_russia(geom):
        europe_lonlat = box(20, 35, 60, 75)
        europe_3035 = gpd.GeoSeries([europe_lonlat], crs=4326).to_crs(3035).iloc[0]
        return geom.intersection(europe_3035)

    rus = admin[admin["country"] == "RUS"].copy()
    admin = admin[admin["country"] != "RUS"]
    rus["geometry"] = rus.geometry.apply(cut_russia)
    rus = rus[~rus.geometry.is_empty]
    admin = pd.concat([admin, rus], ignore_index=True)

    minx, miny, maxx, maxy = 900000, 1000000, 7000000, 6500000
    admin = admin.cx[minx:maxx, miny:maxy]

    admin["geometry"] = admin.geometry.apply(remove_holes).buffer(0)
    land = merge_small_absolute(admin).reset_index(drop=True)
    return land


def resolve_query_path() -> str:
    """Prefer query.csv; otherwise pick the last query*.csv in this folder."""
    if os.path.exists(QUERY_PATH):
        return QUERY_PATH
    candidates = sorted(glob.glob(os.path.join(BASE, "query*.csv")))
    if candidates:
        return candidates[-1]
    raise FileNotFoundError("No query CSV found (expected query*.csv in src/)")


def load_population() -> pd.DataFrame:
    qpath = resolve_query_path()
    df = pd.read_csv(qpath).reset_index().rename(columns={"index": "source_index"})
    df["population"] = pd.to_numeric(df["population"], errors="coerce")
    df["populationDate"] = pd.to_datetime(df["populationDate"], errors="coerce")
    if "countryLabel" not in df.columns:
        df["countryLabel"] = ""
    if "regionLabel" not in df.columns:
        raise KeyError("Missing required column 'regionLabel' in population CSV")
    if "iso" not in df.columns:
        df["iso"] = ""

    df["norm_iso"] = df["iso"].apply(normalize_iso)
    df["norm_region"] = df["regionLabel"].apply(normalize)
    df["norm_country"] = df["countryLabel"].apply(normalize)

    df = df.sort_values(["norm_iso", "norm_region", "norm_country", "populationDate"])

    frames = []
    df_iso = df[df["norm_iso"] != ""]
    df_rest = df[df["norm_iso"] == ""]
    if not df_iso.empty:
        frames.append(df_iso.groupby("norm_iso", as_index=False).last())
    if not df_rest.empty:
        frames.append(df_rest.groupby(["norm_region", "norm_country"], as_index=False).last())

    latest = pd.concat(frames, ignore_index=True, sort=False) if frames else df.head(0)
    return latest.rename(columns={"region": "region_uri"})


def build_lookup(land: gpd.GeoDataFrame):
    lookup_full: Dict[Tuple[str, str], List[int]] = {}
    lookup_region: Dict[str, List[int]] = {}
    region_index: List[Tuple[int, str]] = []
    country_map: Dict[int, str] = {}
    iso_map: Dict[str, int] = {}

    iso_col = None
    for candidate in ["iso_3166_2", "iso", "adm1_code", "code_hasc"]:
        if candidate in land.columns:
            iso_col = candidate
            break

    for pid, row in land.iterrows():
        n_country = normalize(row.get("admin", "")) or normalize(row.get("country", ""))
        country_map[pid] = n_country

        if iso_col:
            n_iso = normalize_iso(row.get(iso_col, ""))
            if n_iso:
                iso_map[n_iso] = pid

        for candidate in [row.get("name_en"), row.get("name"), row.get("name_alt")]:
            n_region = normalize(candidate)
            if not n_region:
                continue
            lookup_full.setdefault((n_region, n_country), []).append(pid)
            lookup_region.setdefault(n_region, []).append(pid)
        main_name = normalize(row.get("name_en") or row.get("name"))
        if main_name:
            region_index.append((pid, main_name))

    return lookup_full, lookup_region, region_index, country_map, iso_map


def fuzzy_region_match(norm_region: str, region_index: List[Tuple[int, str]]) -> List[int]:
    if not norm_region:
        return []

    hits = [pid for pid, name in region_index if norm_region in name or name in norm_region]
    if hits:
        return hits

    best = []
    best_ratio = 0.0
    for pid, name in region_index:
        r = difflib.SequenceMatcher(None, norm_region, name).ratio()
        if r > best_ratio and r >= 0.8:
            best = [pid]
            best_ratio = r
    return best


def match_population_to_land(pop_df: pd.DataFrame, lookup_full, lookup_region, region_index, country_map, iso_map):
    matched = {}  # pid -> (row, method, priority)
    unmatched = []
    priority = {
        "iso": 4,
        "exact_country": 3,
        "region_only": 2,
        "fuzzy_contain": 1,
        "fuzzy_best": 0,
    }

    for _, row in pop_df.iterrows():
        key = (row["norm_region"], row["norm_country"])
        hits = None
        method = "exact_country"

        # Highest-priority: ISO 3166-2 exact match if present
        if row.get("norm_iso"):
            pid = iso_map.get(row["norm_iso"])
            if pid is not None:
                hits = [pid]
                method = "iso"

        if hits is None:
            hits = lookup_full.get(key)
            method = "exact_country"

        if not hits:
            hits = lookup_region.get(row["norm_region"])
            method = "region_only"

        if not hits:
            hits = fuzzy_region_match(row["norm_region"], region_index)
            method = "fuzzy_contain"

        if not hits:
            best_pid = None
            best_ratio = 0.0
            for pid, name in region_index:
                r = difflib.SequenceMatcher(None, row["norm_region"], name).ratio()
                if r > best_ratio:
                    best_ratio = r
                    best_pid = pid
            if best_ratio >= 0.55 and best_pid is not None:
                hits = [best_pid]
                method = "fuzzy_best"

        # If we have a country in the source, enforce it on fuzzy matches
        if hits and row["norm_country"]:
            hits = [pid for pid in hits if country_map.get(pid, "") == row["norm_country"]]
            if not hits:
                method = "unmatched"

        if not hits:
            unmatched.append((row["regionLabel"], row["countryLabel"]))
            continue

        pid = hits[0]
        existing = matched.get(pid)
        if existing is None:
            matched[pid] = (row, method, priority.get(method, -1))
        else:
            _, _, cur_pri = existing
            new_pri = priority.get(method, -1)
            replace = False
            if new_pri > cur_pri:
                replace = True
            elif new_pri == cur_pri and (
                pd.notna(row["populationDate"])
                and row["populationDate"] > existing[0]["populationDate"]
            ):
                replace = True
            if replace:
                matched[pid] = (row, method, new_pri)

    return matched, unmatched


def build_output_rows(land: gpd.GeoDataFrame, matched: Dict[int, pd.Series]):
    out_rows = []
    debug_rows = []
    for pid, prow in land.iterrows():
        entry = matched.get(pid)
        match = entry[0] if entry is not None else None
        method = entry[1] if entry is not None else "unmatched"
        source = "matched" if method == "exact_country" else method
        out_rows.append({
            "province_id": pid,
            "province_name": prow.get("name_en") or prow.get("name"),
            "country": prow.get("admin") or prow.get("country"),
            "population": int(match["population"]) if match is not None and pd.notna(match["population"]) else "",
            "population_date": (
                match["populationDate"].date().isoformat()
                if match is not None and pd.notna(match["populationDate"])
                else ""
            ),
            "wikidata_uri": match["region_uri"] if match is not None else "",
            "population_source": source if match is not None else "unmatched",
        })
        debug_rows.append({
            "province_id": pid,
            "province_name": prow.get("name_en") or prow.get("name"),
            "province_country": prow.get("admin") or prow.get("country"),
            "match_method": source if match is not None else "unmatched",
            "matched_population": int(match["population"]) if match is not None and pd.notna(match["population"]) else "",
            "matched_population_date": (
                match["populationDate"].date().isoformat()
                if match is not None and pd.notna(match["populationDate"])
                else ""
            ),
            "source_region": match["regionLabel"] if match is not None else "",
            "source_country": match["countryLabel"] if match is not None else "",
            "source_population": match["population"] if match is not None else "",
            "source_population_date": (
                match["populationDate"].date().isoformat()
                if match is not None and pd.notna(match["populationDate"])
                else ""
            ),
            "source_index": match["source_index"] if match is not None else "",
        })
    return out_rows, debug_rows


def generate_population_dataset(
    land: Optional[gpd.GeoDataFrame] = None,
    out_path: str = OUT_PATH,
    write_csv: bool = True,
    fill_missing: bool = True,
    debug_path: Optional[str] = None,
):
    """
    Returns:
        pop_values: {pid: population} for matched provinces (with fills if enabled)
        rows: list of dicts ready for CSV export
        unmatched: list of (regionLabel, countryLabel) that did not match
    """
    land = land if land is not None else load_land()
    pop_df = load_population()
    lookup_full, lookup_region, region_index, country_map, iso_map = build_lookup(land)
    matched, unmatched = match_population_to_land(pop_df, lookup_full, lookup_region, region_index, country_map, iso_map)

    rows, debug_rows = build_output_rows(land, matched)

    pop_values = {
        pid: float(row[0]["population"])
        for pid, row in matched.items()
        if pd.notna(row[0]["population"])
    }

    if fill_missing:
        country_values: Dict[str, List[float]] = {}
        for pid, val in pop_values.items():
            country = (land.loc[pid]["admin"] if "admin" in land.columns else land.loc[pid].get("country")) or ""
            country_values.setdefault(country, []).append(val)

        country_median = {c: median(vs) for c, vs in country_values.items() if vs}
        global_vals = list(pop_values.values())
        global_median = median(global_vals) if global_vals else 0.0

        for row in rows:
            if row["population"] == "" or row["population"] == 0:
                c = row["country"] or ""
                fallback = country_median.get(c, global_median)
                val = int(fallback) if fallback else 1
                val += (row["province_id"] % 997)
                row["population"] = val
                row["population_source"] = "filled_country" if c in country_median else "filled_global"
                pop_values[row["province_id"]] = float(val)

    for row in rows:
        pid = row["province_id"]
        if pid not in pop_values or pop_values[pid] <= 0:
            base = row["population"] if row["population"] else 1
            val = int(base) + (pid % 991)
            row["population"] = val
            row["population_source"] = row.get("population_source", "filled_global")
            pop_values[pid] = float(val)

    if write_csv:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        pd.DataFrame(rows).to_csv(out_path, sep=";", index=False)
        if debug_path:
            pd.DataFrame(debug_rows).to_csv(debug_path, sep=";", index=False)

    return pop_values, rows, unmatched, debug_rows


def main():
    pop_values, rows, unmatched, debug_rows = generate_population_dataset(debug_path=os.path.join(OUT_DIR, "Population_debug.csv"))
    print(f"[POP] Written {len(rows)} province entries to {OUT_PATH}")
    if unmatched:
        print(f"[POP] Unmatched regions: {len(unmatched)} (showing first 10)")
        for name, country in unmatched[:10]:
            print(f" - {name} ({country})")
    if not pop_values:
        print("[POP] Warning: no population values matched.")


if __name__ == "__main__":
    main()
