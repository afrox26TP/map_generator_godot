import os
import re
import glob
import unicodedata
import difflib
from typing import Dict, List, Optional, Set, Tuple
from statistics import median

import geopandas as gpd
import pandas as pd
from shapely.geometry import box, Polygon, MultiPolygon

BASE = os.path.dirname(os.path.abspath(__file__))
QUERY_PATH = os.path.join(BASE, "query.csv")
SHAPE_PATH = os.path.join(BASE, "ne_10m_admin_1_states_provinces.shp")
OUT_DIR = os.path.join(BASE, "opengs_export")
OUT_PATH = os.path.join(OUT_DIR, "Population.csv")
ALIAS_PATH = os.path.join(BASE, "population_aliases_starter.csv")
COUNTRY_TOTALS_PATH = os.path.join(BASE, "country_population_totals.csv")
PROVINCE_SEED_PATH = os.path.join(BASE, "province_population_seed.csv")

# Aliases are only applied when status is one of these values.
ALIAS_ENABLED_STATUSES = {"suggested", "approved", "active"}
USE_CONSISTENT_DISTRIBUTION = True
TARGET_POP_YEAR = 2023
MIN_POP_YEAR = 2000
# Only these match methods are trusted to estimate density for imputation.
DENSITY_CONFIDENT_METHODS = {"iso", "exact_country", "region_only"}

# Built-in aliases normalize common UK naming variants in source datasets.
DEFAULT_COUNTRY_ALIASES = {
    "great britain": "united kingdom",
    "britain": "united kingdom",
    "england": "united kingdom",
    "scotland": "united kingdom",
    "wales": "united kingdom",
    "northern ireland": "united kingdom",
    "uk": "united kingdom",
}

# These countries are known to have mixed/cross-level source rows in query.csv.
# For them we use seed/area weights + official totals for stable province values.
FORCE_SEED_ONLY_COUNTRIES = {"FRA", "ESP", "GBR"}
FORCE_WEIGHT_EXPONENT = 0.85
REGION_MATCH_MIN_SCORE = 0.82

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


def load_aliases() -> Tuple[Dict[str, str], Dict[Tuple[str, str], Tuple[str, str]]]:
    """Load approved country/region aliases from population_aliases_starter.csv."""
    if not os.path.exists(ALIAS_PATH):
        return {}, {}

    alias_df = pd.read_csv(ALIAS_PATH, sep=";", encoding="utf-8-sig")
    required = {
        "alias_type",
        "source_country",
        "source_region",
        "target_country",
        "target_region",
        "status",
    }
    missing = required.difference(alias_df.columns)
    if missing:
        print(f"[POP] Alias file missing columns {sorted(missing)}; aliases disabled.")
        return {}, {}

    country_aliases: Dict[str, str] = {}
    region_aliases: Dict[Tuple[str, str], Tuple[str, str]] = {}

    for _, row in alias_df.iterrows():
        status = normalize(str(row.get("status", "")))
        if status and status not in ALIAS_ENABLED_STATUSES:
            continue

        alias_type = normalize(str(row.get("alias_type", "")))
        src_country = normalize(row.get("source_country", ""))
        src_region = normalize(row.get("source_region", ""))
        tgt_country = normalize(row.get("target_country", ""))
        tgt_region = normalize(row.get("target_region", ""))

        if alias_type == "country":
            if src_country and tgt_country:
                country_aliases[src_country] = tgt_country
            continue

        if alias_type == "region":
            if src_region and (tgt_country or tgt_region):
                region_aliases[(src_country, src_region)] = (tgt_country, tgt_region)

    if country_aliases or region_aliases:
        print(
            f"[POP] Loaded aliases: {len(country_aliases)} country, "
            f"{len(region_aliases)} region"
        )
    return country_aliases, region_aliases


def apply_aliases(
    pop_df: pd.DataFrame,
    country_aliases: Dict[str, str],
    region_aliases: Dict[Tuple[str, str], Tuple[str, str]],
) -> pd.DataFrame:
    """Apply configured aliases to normalized country/region fields before matching."""
    if pop_df.empty:
        return pop_df
    if not country_aliases and not region_aliases and not DEFAULT_COUNTRY_ALIASES:
        return pop_df

    pop_df = pop_df.copy()
    out_country: List[str] = []
    out_region: List[str] = []
    country_changes = 0
    region_rules = 0

    effective_country_aliases = dict(DEFAULT_COUNTRY_ALIASES)
    effective_country_aliases.update(country_aliases)

    for _, row in pop_df.iterrows():
        src_country = row["norm_country"]
        src_region = row["norm_region"]

        country_norm = effective_country_aliases.get(src_country, src_country)
        if country_norm != src_country:
            country_changes += 1

        region_norm = src_region
        alias = region_aliases.get((src_country, src_region))
        if alias is None:
            alias = region_aliases.get((country_norm, src_region))
        if alias is None:
            alias = region_aliases.get(("", src_region))

        if alias is not None:
            alias_country, alias_region = alias
            if alias_country:
                country_norm = alias_country
            if alias_region:
                region_norm = alias_region
            region_rules += 1

        out_country.append(country_norm)
        out_region.append(region_norm)

    pop_df["norm_country"] = out_country
    pop_df["norm_region"] = out_region

    if country_changes or region_rules:
        print(f"[POP] Alias applications: country={country_changes}, region={region_rules}")

    return pop_df


def filter_current_entities(pop_df: pd.DataFrame, allowed_countries: Optional[Set[str]]) -> pd.DataFrame:
    """
    Option 1: keep only current-like entities.
    - drop non-positive populations
    - drop unresolved QID region labels
    - drop very old observations
    - keep only countries represented in current Natural Earth land set (or ISO-coded rows)
    """
    if pop_df.empty:
        return pop_df

    before = len(pop_df)
    df = pop_df.copy()

    df = df[pd.notna(df["population"]) & (df["population"] > 0)]
    df = df[df["norm_region"] != ""]

    region_raw = df["regionLabel"].fillna("").astype(str).str.strip()
    df = df[~region_raw.str.match(r"^Q\\d+$", case=False, na=False)]

    if "populationDate" in df.columns:
        date_ok = df["populationDate"].isna() | (df["populationDate"].dt.year >= MIN_POP_YEAR)
        df = df[date_ok]

    if allowed_countries:
        allowed = set(allowed_countries)
        df = df[(df["norm_iso"] != "") | (df["norm_country"].isin(allowed))]
    else:
        df = df[(df["norm_iso"] != "") | (df["norm_country"] != "")]

    removed = before - len(df)
    if removed > 0:
        print(f"[POP] Current-entity filter removed {removed} rows.")

    return df


def load_country_totals(land: gpd.GeoDataFrame, target_year: int) -> Dict[str, float]:
    """Load optional official country totals used for country calibration."""
    if not os.path.exists(COUNTRY_TOTALS_PATH):
        return {}

    totals_df = pd.read_csv(COUNTRY_TOTALS_PATH, sep=";")
    if len(totals_df.columns) == 1:
        totals_df = pd.read_csv(COUNTRY_TOTALS_PATH)

    def _looks_like_iso3(series: pd.Series) -> bool:
        sample = series.dropna().astype(str).str.strip().head(20)
        if sample.empty:
            return False
        ratio = sample.str.fullmatch(r"[A-Za-z]{3}").mean()
        return bool(ratio >= 0.8)

    country_col = next(
        (c for c in ["country_iso3", "iso3", "country", "country_code"] if c in totals_df.columns),
        None,
    )
    pop_col = next(
        (c for c in ["population", "total_population", "pop"] if c in totals_df.columns),
        None,
    )
    year_col = next((c for c in ["year", "population_year"] if c in totals_df.columns), None)

    if country_col is None or pop_col is None:
        raw_df = pd.read_csv(COUNTRY_TOTALS_PATH, sep=";", header=None)
        if raw_df.shape[1] >= 2 and _looks_like_iso3(raw_df.iloc[:, 0]):
            rename = {0: "country_iso3", 1: "population"}
            if raw_df.shape[1] >= 3:
                rename[2] = "year"
            if raw_df.shape[1] >= 4:
                rename[3] = "source"

            totals_df = raw_df.rename(columns=rename)
            country_col = "country_iso3"
            pop_col = "population"
            year_col = "year" if "year" in totals_df.columns else None
            print("[POP] country_population_totals.csv loaded as headerless format.")
        else:
            print("[POP] country_population_totals.csv missing required columns; ignoring official totals.")
            return {}

    land_isos = set(str(v).upper() for v in land["country"].dropna().unique()) if "country" in land.columns else set()
    name_to_iso: Dict[str, str] = {}
    if "country" in land.columns:
        for _, row in land[["country", "admin"]].drop_duplicates().iterrows():
            iso = str(row.get("country", "")).upper().strip()
            admin_name = normalize(row.get("admin", ""))
            if iso:
                name_to_iso[normalize(iso)] = iso
                if admin_name:
                    name_to_iso[admin_name] = iso

    selected_rows = []
    for _, group in totals_df.groupby(country_col):
        grp = group.copy()
        if year_col and year_col in grp.columns:
            grp[year_col] = pd.to_numeric(grp[year_col], errors="coerce")
            dated = grp[pd.notna(grp[year_col])]
            if dated.empty:
                pick = grp.iloc[-1]
            else:
                at_or_before = dated[dated[year_col] <= target_year]
                pick = (at_or_before if not at_or_before.empty else dated).sort_values(year_col).iloc[-1]
        else:
            pick = grp.iloc[-1]
        selected_rows.append(pick)

    selected_df = pd.DataFrame(selected_rows)
    totals: Dict[str, float] = {}

    for _, row in selected_df.iterrows():
        raw_country = str(row.get(country_col, "")).strip()
        pop = pd.to_numeric(row.get(pop_col), errors="coerce")
        if pd.isna(pop) or pop <= 0:
            continue

        iso = None
        if re.fullmatch(r"[A-Za-z]{3}", raw_country):
            cand = raw_country.upper()
            if cand in land_isos:
                iso = cand

        if iso is None:
            iso = name_to_iso.get(normalize(raw_country))

        if iso is not None:
            totals[iso] = float(pop)

    if totals:
        print(f"[POP] Loaded {len(totals)} official country totals.")
    return totals


def load_province_seed_weights(land: gpd.GeoDataFrame) -> Dict[int, float]:
    """
    Baseline weights for option 3.
    - default: province area (stable full-coverage fallback)
    - optional override: province_population_seed.csv (e.g., raster sums)
    """
    weights = {
        pid: max(float(row.geometry.area), 1.0)
        for pid, row in land.iterrows()
        if row.geometry is not None
    }

    if not os.path.exists(PROVINCE_SEED_PATH):
        return weights

    seed_df = pd.read_csv(PROVINCE_SEED_PATH, sep=";")
    if len(seed_df.columns) == 1:
        seed_df = pd.read_csv(PROVINCE_SEED_PATH)

    if "province_id" not in seed_df.columns:
        print("[POP] province_population_seed.csv missing province_id; ignoring seed overrides.")
        return weights

    seed_col = next((c for c in ["seed_population", "population", "weight"] if c in seed_df.columns), None)
    if seed_col is None:
        print("[POP] province_population_seed.csv missing seed column; ignoring seed overrides.")
        return weights

    used = 0
    for _, row in seed_df.iterrows():
        pid = pd.to_numeric(row.get("province_id"), errors="coerce")
        seed = pd.to_numeric(row.get(seed_col), errors="coerce")
        if pd.isna(pid) or pd.isna(seed) or seed <= 0:
            continue
        ipid = int(pid)
        if ipid in weights:
            weights[ipid] = float(seed)
            used += 1

    if used:
        print(f"[POP] Applied {used} province seed overrides.")
    return weights


def allocate_country_total(province_ids: List[int], weights: Dict[int, float], target_total: float) -> Dict[int, int]:
    """Allocate integer population across provinces by weight, preserving country total."""
    if not province_ids:
        return {}

    target = max(int(round(target_total)), len(province_ids))
    allocations = {pid: 1 for pid in province_ids}
    remaining = target - len(province_ids)
    if remaining <= 0:
        return allocations

    safe_weights = {pid: max(weights.get(pid, 1.0), 1e-9) for pid in province_ids}
    total_weight = sum(safe_weights.values())
    consumed = 0
    fractions: List[Tuple[int, float]] = []

    for pid in province_ids:
        exact = remaining * safe_weights[pid] / total_weight
        base = int(exact)
        allocations[pid] += base
        consumed += base
        fractions.append((pid, exact - base))

    rest = remaining - consumed
    if rest > 0:
        fractions.sort(key=lambda item: item[1], reverse=True)
        for i in range(rest):
            allocations[fractions[i % len(fractions)][0]] += 1

    return allocations


def _region_similarity(a: str, b: str) -> float:
    """Combined lexical similarity for cross-language region labels."""
    if not a or not b:
        return 0.0
    ratio = difflib.SequenceMatcher(None, a, b).ratio()
    ta = set(a.split())
    tb = set(b.split())
    token_overlap = (len(ta & tb) / max(len(ta), len(tb))) if ta and tb else 0.0
    return max(ratio, token_overlap)


def _land_region_candidates(row: pd.Series) -> List[str]:
    vals: List[str] = []
    for col in ["region", "geonunit", "region_sub", "gn_region"]:
        n = normalize(row.get(col, ""))
        if n and n not in vals:
            vals.append(n)
    return vals


def build_region_guided_baseline(
    iso3: str,
    pids: List[int],
    land: gpd.GeoDataFrame,
    pop_df: Optional[pd.DataFrame],
    weights: Dict[int, float],
) -> Tuple[Dict[int, float], Dict[int, str], int]:
    """
    For coarse-source countries, use country-region totals (e.g. FRA regions,
    ESP autonomous communities, GBR geonunit) and split them to provinces.
    """
    if pop_df is None or pop_df.empty or not pids:
        return {}, {}, 0

    country_names = {
        normalize(land.loc[pid].get("admin", ""))
        for pid in pids
    }
    country_names = {c for c in country_names if c}
    if not country_names:
        return {}, {}, 0

    region_rows = pop_df[
        pop_df["norm_country"].isin(country_names)
        & pd.notna(pop_df["population"])
        & (pop_df["population"] > 0)
        & (pop_df["norm_region"] != "")
    ].copy()
    if region_rows.empty:
        return {}, {}, 0

    region_rows = region_rows.sort_values("populationDate")
    region_totals: Dict[str, float] = {}
    for _, row in region_rows.iterrows():
        region_totals[row["norm_region"]] = float(row["population"])

    available_regions = list(region_totals.keys())
    if not available_regions:
        return {}, {}, 0

    region_to_pids: Dict[str, List[int]] = {}
    for pid in pids:
        row = land.loc[pid]
        candidates = _land_region_candidates(row)
        if not candidates:
            continue

        key = next((c for c in candidates if c in region_totals), None)
        if key is None:
            best_key = None
            best_score = 0.0
            for c in candidates:
                for reg in available_regions:
                    score = _region_similarity(c, reg)
                    if score > best_score:
                        best_score = score
                        best_key = reg
            if best_key is not None and best_score >= REGION_MATCH_MIN_SCORE:
                key = best_key

        if key is not None:
            region_to_pids.setdefault(key, []).append(pid)

    used_regions = [rk for rk in region_to_pids if rk in region_totals]
    covered = sum(len(region_to_pids[rk]) for rk in used_regions)

    # Require minimum coverage so we don't overfit on sparse accidental matches.
    if len(used_regions) < 2 or covered < max(2, int(0.2 * len(pids))):
        return {}, {}, 0

    baseline: Dict[int, float] = {}
    baseline_source: Dict[int, str] = {}

    split_weights = {
        pid: max(weights.get(pid, 1.0), 1.0) ** FORCE_WEIGHT_EXPONENT
        for pid in pids
    }

    for region_key in used_regions:
        region_pids = region_to_pids[region_key]
        alloc = allocate_country_total(region_pids, split_weights, region_totals[region_key])
        for pid, val in alloc.items():
            baseline[pid] = float(val)
            baseline_source[pid] = "region_seed_distribution"

    return baseline, baseline_source, len(used_regions)


def build_consistent_population(
    land: gpd.GeoDataFrame,
    matched: Dict[int, Tuple[pd.Series, str, int]],
    target_year: int,
    pop_df: Optional[pd.DataFrame] = None,
) -> Tuple[Dict[int, float], Dict[int, str]]:
    """
    Option 3 (province-first):
    1) keep matched province populations as baseline values
    2) impute only missing provinces using country/global density and seed weights
    3) calibrate to official country totals when provided
    """
    weights = load_province_seed_weights(land)
    official_totals = load_country_totals(land, target_year)

    matched_pop_by_pid: Dict[int, float] = {}
    matched_method_by_pid: Dict[int, str] = {}
    for pid, entry in matched.items():
        src_row = entry[0]
        match_method = entry[1]
        pop = pd.to_numeric(src_row.get("population"), errors="coerce")
        if pd.isna(pop) or pop <= 0:
            continue
        matched_pop_by_pid[pid] = float(pop)
        matched_method_by_pid[pid] = match_method

    country_to_pids: Dict[str, List[int]] = {}
    for pid, row in land.iterrows():
        iso3 = str(row.get("country", "")).upper().strip()
        if not iso3:
            continue
        country_to_pids.setdefault(iso3, []).append(pid)

    trusted_global = [
        pid
        for pid in matched_pop_by_pid
        if matched_method_by_pid.get(pid) in DENSITY_CONFIDENT_METHODS
    ]
    density_source_global = trusted_global if trusted_global else list(matched_pop_by_pid.keys())

    matched_pop_total = 0.0
    matched_weight_total = 0.0
    for pid in density_source_global:
        matched_pop_total += matched_pop_by_pid[pid]
        matched_weight_total += max(weights.get(pid, 1.0), 1.0)

    global_density = (matched_pop_total / matched_weight_total) if matched_weight_total > 0 else 1e-6

    pop_values: Dict[int, float] = {}
    source_by_pid: Dict[int, str] = {}

    for iso3, pids in country_to_pids.items():
        force_seed_only = (
            iso3 in FORCE_SEED_ONLY_COUNTRIES
            and official_totals.get(iso3, 0.0) > 0
        )

        if force_seed_only:
            baseline, baseline_source, used_regions = build_region_guided_baseline(
                iso3=iso3,
                pids=pids,
                land=land,
                pop_df=pop_df,
                weights=weights,
            )

            split_weights = {
                pid: max(weights.get(pid, 1.0), 1.0) ** FORCE_WEIGHT_EXPONENT
                for pid in pids
            }

            if baseline:
                print(
                    f"[POP] {iso3}: using region-guided baseline ({used_regions} matched regions)."
                )
                remaining = [pid for pid in pids if pid not in baseline]
                if remaining:
                    used_weight = sum(split_weights[pid] for pid in baseline)
                    used_pop = sum(baseline.values())
                    fill_density = (used_pop / used_weight) if used_weight > 0 else global_density
                    for pid in remaining:
                        baseline[pid] = max(split_weights[pid] * fill_density, 1.0)
                        baseline_source[pid] = "region_imputed_density"
            else:
                print(
                    f"[POP] {iso3}: region guide unavailable, using seed baseline with exponent."
                )
                for pid in pids:
                    baseline[pid] = max(split_weights[pid], 1.0)
                    baseline_source[pid] = "seed_area_distribution"

            if iso3 in official_totals and official_totals[iso3] > 0:
                allocations = allocate_country_total(pids, baseline, official_totals[iso3])
                for pid, val in allocations.items():
                    pop_values[pid] = float(val)
                    source_label = baseline_source.get(pid, "")
                    if source_label.startswith("region_"):
                        source_by_pid[pid] = "region_scaled_official"
                    elif source_label == "seed_area_distribution":
                        source_by_pid[pid] = "seed_area_scaled_official"
                    else:
                        source_by_pid[pid] = "imputed_scaled_official"
                continue

            for pid in pids:
                pop_values[pid] = float(max(int(round(baseline.get(pid, 1.0))), 1))
                source_by_pid[pid] = baseline_source.get(pid, "seed_area_distribution")
            continue

        matched_pids = [pid for pid in pids if pid in matched_pop_by_pid]
        unmatched_pids = [pid for pid in pids if pid not in matched_pop_by_pid]

        trusted_country = [
            pid
            for pid in matched_pids
            if matched_method_by_pid.get(pid) in DENSITY_CONFIDENT_METHODS
        ]
        use_country_density = bool(trusted_country)
        if use_country_density:
            matched_total = sum(matched_pop_by_pid[pid] for pid in trusted_country)
            matched_weight = sum(max(weights.get(pid, 1.0), 1.0) for pid in trusted_country)
            country_density = (matched_total / matched_weight) if matched_weight > 0 else global_density
        else:
            country_density = global_density

        baseline: Dict[int, float] = {}
        baseline_source: Dict[int, str] = {}

        for pid in matched_pids:
            baseline[pid] = matched_pop_by_pid[pid]
            baseline_source[pid] = "matched_province"

        for pid in unmatched_pids:
            seed_w = max(weights.get(pid, 1.0), 1.0)
            if force_seed_only:
                baseline[pid] = seed_w
                baseline_source[pid] = "seed_area_distribution"
            else:
                baseline[pid] = max(seed_w * country_density, 1.0)
                baseline_source[pid] = "imputed_country_density" if use_country_density else "imputed_global_density"

        if iso3 in official_totals and official_totals[iso3] > 0:
            allocations = allocate_country_total(pids, baseline, official_totals[iso3])
            for pid, val in allocations.items():
                pop_values[pid] = float(val)
                source_label = baseline_source.get(pid, "")
                if source_label.startswith("matched"):
                    source_by_pid[pid] = "matched_scaled_official"
                elif source_label == "seed_area_distribution":
                    source_by_pid[pid] = "seed_area_scaled_official"
                else:
                    source_by_pid[pid] = "imputed_scaled_official"
            continue

        for pid in pids:
            pop_values[pid] = float(max(int(round(baseline.get(pid, 1.0))), 1))
            source_by_pid[pid] = baseline_source.get(pid, "imputed_global_density")

    print(f"[POP] Consistent distribution built for {len(country_to_pids)} countries.")
    return pop_values, source_by_pid


def load_population(allowed_countries: Optional[Set[str]] = None) -> pd.DataFrame:
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

    country_aliases, region_aliases = load_aliases()
    df = apply_aliases(df, country_aliases, region_aliases)
    df = filter_current_entities(df, allowed_countries)

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

    region_tokens = [tok for tok in norm_region.split() if tok]
    region_token_set = set(region_tokens)

    hits: List[int] = []
    for pid, name in region_index:
        name_tokens = [tok for tok in name.split() if tok]
        name_token_set = set(name_tokens)
        if not name_token_set:
            continue

        # Token containment avoids false positives like "aragon" -> "tarragona".
        if region_token_set == name_token_set:
            hits.append(pid)
            continue
        if region_token_set.issubset(name_token_set) and len(region_token_set) >= 2:
            hits.append(pid)
            continue
        if name_token_set.issubset(region_token_set):
            hits.append(pid)

    if hits:
        return hits

    return []


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
            best_name = ""
            best_ratio = 0.0
            for pid, name in region_index:
                r = difflib.SequenceMatcher(None, row["norm_region"], name).ratio()
                if r > best_ratio:
                    best_ratio = r
                    best_pid = pid

                    best_name = name

            src_name = row["norm_region"]
            src_tokens = [tok for tok in src_name.split() if tok]
            best_tokens = [tok for tok in best_name.split() if tok]
            single_token_mode = len(src_tokens) == 1 and len(best_tokens) == 1
            min_ratio = 0.9 if single_token_mode else 0.8
            length_ok = (abs(len(src_name) - len(best_name)) <= 2) if single_token_mode else True

            if best_ratio >= min_ratio and best_pid is not None and length_ok:
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
    lookup_full, lookup_region, region_index, country_map, iso_map = build_lookup(land)
    pop_df = load_population(allowed_countries=set(country_map.values()))
    matched, unmatched = match_population_to_land(pop_df, lookup_full, lookup_region, region_index, country_map, iso_map)

    rows, debug_rows = build_output_rows(land, matched)

    if USE_CONSISTENT_DISTRIBUTION:
        pop_values, source_by_pid = build_consistent_population(
            land,
            matched,
            target_year=TARGET_POP_YEAR,
            pop_df=pop_df,
        )
        for row in rows:
            pid = row["province_id"]
            row["population"] = int(pop_values.get(pid, 1.0))
            row["population_source"] = source_by_pid.get(pid, "calibrated_density")
            if not row.get("population_date"):
                row["population_date"] = f"{TARGET_POP_YEAR}-01-01"
    else:
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
