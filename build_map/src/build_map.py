# =====================================================================
# IMPORTS + CONFIG
# =====================================================================

import geopandas as gpd
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import re
import unicodedata

from shapely.geometry import box, Point, MultiPoint, Polygon, MultiPolygon
from shapely.ops import unary_union, voronoi_diagram
import os, random

DEBUG = True

# PART 2.65 is experimental and may introduce visual artifacts in raster output.
# Keep it disabled by default until fully tuned.
ENABLE_INLAND_DISCONNECTED_MERGE = False

def debug(msg):
    if DEBUG:
        print(f"[DEBUG] {msg}")

BASE = os.path.dirname(os.path.abspath(__file__))


# =====================================================================
# PART 1 — LOAD ADMIN1 + FIX EUROPE + CUT RUSSIA + ADD CAUCASUS + ISLANDS
# =====================================================================

debug("PART 1 START — loading & filtering admin1")

admin = gpd.read_file(os.path.join(BASE, "ne_10m_admin_1_states_provinces.shp"))
# AI-GENERATED
admin = admin.to_crs(3035)
admin["geometry"] = admin.geometry.buffer(0)
# AI-END

# -----------------------------
# LIST OF COUNTRIES TO KEEP
# -----------------------------
EUROPE_COUNTRIES = [
    # Core EU + EEA
    "ISL","IRL","GBR","PRT","ESP","FRA","AND","BEL","NLD","LUX",
    "DEU","CHE","AUT","LIE","ITA","SMR","MLT",
    "DNK","NOR","SWE","FIN",
    "EST","LVA","LTU",
    "POL","CZE","SVK","HUN",
    "SVN","HRV","BIH","SRB","MNE","MKD","ALB","KOS",
    "GRC","CYP",  # Cyprus added

    # East
    "BGR","ROU","MDA","UKR","BLR",

    # Russia (will cut)
    "RUS",

    # Caucasus (add back)
    "ARM","GEO","AZE",
    
    # Turkey (only part will be visible after cropping)
    "TUR"
]


# Country capital fallback points (lon, lat in EPSG:4326).
# Used when admin1 metadata does not explicitly mark a capital province.
COUNTRY_CAPITAL_POINTS = {
    "ALB": ("Tirana", 19.8187, 41.3275),
    "AND": ("Andorra la Vella", 1.5218, 42.5063),
    "ARM": ("Yerevan", 44.5152, 40.1872),
    "AUT": ("Vienna", 16.3738, 48.2082),
    "AZE": ("Baku", 49.8671, 40.4093),
    "BEL": ("Brussels", 4.3517, 50.8503),
    "BGR": ("Sofia", 23.3219, 42.6977),
    "BIH": ("Sarajevo", 18.4131, 43.8563),
    "BLR": ("Minsk", 27.5615, 53.9045),
    "CHE": ("Bern", 7.4474, 46.9480),
    "CYP": ("Nicosia", 33.3823, 35.1856),
    "CZE": ("Prague", 14.4378, 50.0755),
    "DEU": ("Berlin", 13.4050, 52.5200),
    "DNK": ("Copenhagen", 12.5683, 55.6761),
    "ESP": ("Madrid", -3.7038, 40.4168),
    "EST": ("Tallinn", 24.7536, 59.4370),
    "FIN": ("Helsinki", 24.9384, 60.1699),
    "FRA": ("Paris", 2.3522, 48.8566),
    "GBR": ("London", -0.1276, 51.5072),
    "GEO": ("Tbilisi", 44.8271, 41.7151),
    "GRC": ("Athens", 23.7275, 37.9838),
    "HRV": ("Zagreb", 15.9819, 45.8150),
    "HUN": ("Budapest", 19.0402, 47.4979),
    "IRL": ("Dublin", -6.2603, 53.3498),
    "ISL": ("Reykjavik", -21.9426, 64.1466),
    "ITA": ("Rome", 12.4964, 41.9028),
    "KOS": ("Pristina", 21.1655, 42.6629),
    "LIE": ("Vaduz", 9.5215, 47.1410),
    "LTU": ("Vilnius", 25.2797, 54.6872),
    "LUX": ("Luxembourg", 6.1319, 49.6116),
    "LVA": ("Riga", 24.1052, 56.9496),
    "MDA": ("Chisinau", 28.8638, 47.0105),
    "MKD": ("Skopje", 21.4316, 41.9973),
    "MLT": ("Valletta", 14.5146, 35.8989),
    "MNE": ("Podgorica", 19.2622, 42.4304),
    "NLD": ("Amsterdam", 4.9041, 52.3676),
    "NOR": ("Oslo", 10.7522, 59.9139),
    "POL": ("Warsaw", 21.0122, 52.2297),
    "PRT": ("Lisbon", -9.1393, 38.7223),
    "ROU": ("Bucharest", 26.1025, 44.4268),
    "RUS": ("Moscow", 37.6173, 55.7558),
    "SMR": ("San Marino", 12.4578, 43.9424),
    "SRB": ("Belgrade", 20.4573, 44.7872),
    "SVK": ("Bratislava", 17.1077, 48.1486),
    "SVN": ("Ljubljana", 14.5058, 46.0569),
    "SWE": ("Stockholm", 18.0686, 59.3293),
    "TUR": ("Ankara", 32.8597, 39.9334),
    "UKR": ("Kyiv", 30.5234, 50.4501),
}

CAPITAL_POINT_FALLBACK_MAX_DISTANCE_M = 150_000
CUSTOM_ISLAND_COUNTRY = "AEO"
CUSTOM_ISLAND_NAME = "Adam Epstein Ostrov"
# Place AEO near Faroe Islands where there's less raster cleanup interference.
# North Atlantic position ensures it stays visible without sea region overlap.
CUSTOM_ISLAND_CENTER_LON = -7.2
CUSTOM_ISLAND_CENTER_LAT = 62.0
CUSTOM_ISLAND_RADIUS_M = 35_000

# Inland safety mask countries: these landlocked regions should never contain sea.
# Helps eliminate occasional topology/raster leaks in central/eastern Europe.
INLAND_NO_SEA_COUNTRIES = {
    "AUT", "HUN", "SVK", "CZE", "CHE", "LUX", "BLR", "MDA", "SRB", "MKD"
}
INLAND_NO_SEA_BUFFER_M = 15_000

admin["country"] = admin["adm0_a3"]
admin = admin[admin["country"].isin(EUROPE_COUNTRIES)].reset_index(drop=True)
debug(f"Regions loaded after country filter: {len(admin)}")


def _clean_optional_text(value):
    # HELPED BY AI
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"", "nan", "none"}:
        return ""
    # AI-END
    return text


def _extract_capital_city_name(row):
    for key in ("capital_city_name", "woe_name", "name_en", "name"):
        text = _clean_optional_text(row.get(key))
        if text:
            return text

    label = _clean_optional_text(row.get("woe_label"))
    if label:
        return label.split(",", 1)[0].strip()

    return ""


def mark_capital_provinces(gdf):
    gdf = gdf.copy()
    type_en = gdf.get("type_en", pd.Series("", index=gdf.index)).fillna("").astype(str)
    # AI-GENERATED
    type_raw = gdf.get("type", pd.Series("", index=gdf.index)).fillna("").astype(str)
    # AI-END
    capital_mask = (
        type_en.str.contains("capital", case=False, regex=False)
        # AI-GENERATED
        | type_raw.str.contains("capital", case=False, regex=False)
        # AI-END
    )
    gdf["is_capital_province"] = capital_mask.astype(int)
    gdf["capital_city_name"] = ""
    # AI-GENERATED
    if capital_mask.any():
        gdf.loc[capital_mask, "capital_city_name"] = gdf.loc[capital_mask].apply(
            _extract_capital_city_name,
            axis=1,
        )
    # AI-END

    unresolved = []
    # AI-GENERATED
    for country, (capital_name, lon, lat) in COUNTRY_CAPITAL_POINTS.items():
        country_mask = gdf["country"] == country
        # HELPED BY AI
        if not country_mask.any():
            continue
        # AI-END
        if int(gdf.loc[country_mask, "is_capital_province"].sum()) > 0:
            continue

        group = gdf.loc[country_mask]
        capital_point = gpd.GeoSeries([Point(lon, lat)], crs=4326).to_crs(gdf.crs).iloc[0]

        contains = group.geometry.contains(capital_point) | group.geometry.touches(capital_point)
        # AI-EDITED
        if contains.any():
            matches = group[contains]
            target_idx = matches.geometry.area.idxmin()
        else:
            distances = group.geometry.distance(capital_point)
            target_idx = distances.idxmin()
            if float(distances.loc[target_idx]) > CAPITAL_POINT_FALLBACK_MAX_DISTANCE_M:
                unresolved.append(country)
                continue
        # AI-END

        gdf.loc[target_idx, "is_capital_province"] = 1
        if not _clean_optional_text(gdf.loc[target_idx, "capital_city_name"]):
            # AI-EDITED
            gdf.loc[target_idx, "capital_city_name"] = capital_name
            # AI-END

    if unresolved:
        debug(f"Capital fallback unresolved countries: {', '.join(sorted(unresolved))}")
    return gdf


def _text_to_shapely_geom(text, cx_m, cy_m, total_width_m, font_path=None):
    # AI-GENERATED
    """Render *text* as a Shapely geometry (union of buffered pixel dots) centred at (cx_m, cy_m)."""
    from PIL import Image as _Im, ImageDraw as _IDraw, ImageFont as _IFont
    from shapely.geometry import Point as _Pt
    from shapely.ops import unary_union as _uu

    IMG_W, IMG_H = 600, 150
    img = _Im.new("L", (IMG_W, IMG_H), 0)
    draw = _IDraw.Draw(img)

    font = None
    for path in ([font_path] if font_path else []) + [
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/Arial Bold.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]:
        try:
            font = _IFont.truetype(path, 110)
            break
        except Exception:
            pass
    if font is None:
        font = _IFont.load_default()

    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((IMG_W - tw) // 2 - bbox[0], (IMG_H - th) // 2 - bbox[1]), text, fill=255, font=font)

    arr = np.array(img)
    ys, xs = np.where(arr > 128)
    if len(xs) == 0:
        return None

    scale = total_width_m / IMG_W          # metres per pixel
    px_cx, px_cy = xs.mean(), ys.mean()

    step = 2                               # subsample every 2nd pixel (denser)
    mask = (ys % step == 0) & (xs % step == 0)
    xs_s, ys_s = xs[mask], ys[mask]

    geo_xs = cx_m + (xs_s - px_cx) * scale
    geo_ys = cy_m - (ys_s - px_cy) * scale   # flip Y axis

    # Use a fixed minimum stroke radius so thin letter parts survive raster cleanup.
    # At final 4096-px map resolution over ~8000 km, 1 px ≈ 2 km, so we need ≥ 3 km radius.
    r = max(scale * step * 1.5, 3_500)
    circles = [_Pt(float(x), float(y)).buffer(r) for x, y in zip(geo_xs, geo_ys)]
    # AI-END
    return _uu(circles)


def add_adam_epstein_island(gdf):
    gdf = gdf.copy()
    if "country" in gdf.columns and (gdf["country"] == CUSTOM_ISLAND_COUNTRY).any():
        return gdf

    center = gpd.GeoSeries(
        [Point(CUSTOM_ISLAND_CENTER_LON, CUSTOM_ISLAND_CENTER_LAT)],
        crs=4326,
    ).to_crs(gdf.crs).iloc[0]

    # Shape = letters "EPSTEIN" rendered as geographic geometry (~190 km wide)
    island_geom = _text_to_shapely_geom(
        "EPSTEIN", center.x, center.y, total_width_m=190_000
    )
    if island_geom is None or island_geom.is_empty:
        island_geom = center.buffer(CUSTOM_ISLAND_RADIUS_M, resolution=24)

    row = {col: None for col in gdf.columns}
    row["geometry"] = island_geom

    if "country" in row:
        row["country"] = CUSTOM_ISLAND_COUNTRY
    if "adm0_a3" in row:
        row["adm0_a3"] = CUSTOM_ISLAND_COUNTRY
    if "name_en" in row:
        row["name_en"] = CUSTOM_ISLAND_NAME
    if "name" in row:
        row["name"] = CUSTOM_ISLAND_NAME
    if "admin" in row:
        row["admin"] = CUSTOM_ISLAND_NAME
    if "type_en" in row:
        row["type_en"] = "Capital island"
    if "type" in row:
        row["type"] = "capital"
    if "woe_name" in row:
        row["woe_name"] = CUSTOM_ISLAND_NAME
    if "woe_label" in row:
        row["woe_label"] = CUSTOM_ISLAND_NAME
    if "capital_city_name" in row:
        row["capital_city_name"] = CUSTOM_ISLAND_NAME
    if "is_capital_province" in row:
        row["is_capital_province"] = 1

    island_gdf = gpd.GeoDataFrame([row], columns=gdf.columns, geometry="geometry", crs=gdf.crs)
    gdf = gpd.GeoDataFrame(pd.concat([gdf, island_gdf], ignore_index=True), geometry="geometry", crs=gdf.crs)

    debug("Custom island added: Adam Epstein Ostrov (AEO)")
    return gdf


# -----------------------------
# FIX: Cut RUSSIA to EUROPE part
# -----------------------------
def cut_russia(geom):
    europe_lonlat = box(20, 35, 60, 75)  # 20E–60E, 35N–75N
    europe_3035 = gpd.GeoSeries([europe_lonlat], crs=4326).to_crs(3035).iloc[0]
    return geom.intersection(europe_3035)

rus = admin[admin["country"] == "RUS"].copy()
admin = admin[admin["country"] != "RUS"]

rus["geometry"] = rus.geometry.apply(cut_russia)
rus = rus[~rus.geometry.is_empty]

admin = pd.concat([admin, rus], ignore_index=True)

# -----------------------------
# REMOVE GEOMETRIES OUTSIDE EUROPE AREA
# -----------------------------
# This bounding box keeps Med islands, Cyprus, Iceland, Caucasus
minx, miny, maxx, maxy = 900000, 1000000, 7000000, 6500000
admin = admin.cx[minx:maxx, miny:maxy]

# Tag capitals after geographic clipping so exported countries retain a capital row.
admin = mark_capital_provinces(admin)
admin = add_adam_epstein_island(admin)
debug(f"Capital provinces tagged: {int(admin['is_capital_province'].sum())}")

debug(f"Final part-1 regions: {len(admin)}")
debug("PART 1 DONE")


# =====================================================================
# PART 2 — CLEAN GEOMETRY
# =====================================================================

debug("PART 2 START — cleaning geometry")

def remove_holes(g):
    if g.geom_type == "Polygon":
        return Polygon(g.exterior)
    elif g.geom_type == "MultiPolygon":
        return MultiPolygon([Polygon(p.exterior) for p in g.geoms])
    return g

admin["geometry"] = admin.geometry.apply(remove_holes)
admin["geometry"] = admin.geometry.buffer(0)

land = admin.copy()
land_union = unary_union(land.geometry)

debug(f"PART 2 DONE — valid regions: {len(land)}")
debug("Before merge small: " + str(len(land)))

# =====================================================================
# PART 2.5 — MERGING OF SMALL REGIONS (ABSOLUTE THRESHOLD ONLY)
# =====================================================================

debug("PART 2.5 START — merging small provinces...")

from shapely.geometry import Polygon, MultiPolygon

# --------------------------
# CONSTANT AREA MERGE THRESHOLD
# --------------------------
MIN_AREA_ABS = 1_000_000_000   # cokoliv menší než 10M m² se sloučí
MIN_ISLET_COMPONENT_AREA_ABS = 50_000_000
MIN_ISLET_COMPONENT_AREA_REL = 0.01


def merge_small_absolute(gdf):
    gdf = gdf.copy()
    if "is_capital_province" not in gdf.columns:
        gdf["is_capital_province"] = 0
    if "capital_city_name" not in gdf.columns:
        gdf["capital_city_name"] = ""
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

            # candidates ONLY in the same country
            candidates = group.drop(idx)
            if candidates.empty:
                # Keep single-province countries intact (e.g., custom islands).
                # Mark as effectively non-small for this pass and stop this group loop.
                group.loc[idx, "area"] = MIN_AREA_ABS
                break

            # merge with nearest polygon
            nearest_idx = candidates.distance(target.geometry).sort_values().index[0]
            merged_geom = target.geometry.union(group.loc[nearest_idx].geometry)
            merged_capital_flag = int(
                bool(group.loc[nearest_idx, "is_capital_province"])
                or bool(target.get("is_capital_province", 0))
            )
            existing_capital_city = _clean_optional_text(
                group.loc[nearest_idx].get("capital_city_name", "")
            )
            target_capital_city = _clean_optional_text(target.get("capital_city_name", ""))
            merged_capital_city = existing_capital_city or target_capital_city

            group.loc[nearest_idx, "geometry"] = merged_geom
            group.loc[nearest_idx, "is_capital_province"] = merged_capital_flag
            group.loc[nearest_idx, "capital_city_name"] = merged_capital_city
            group = group.drop(idx)
            group["area"] = group.geometry.area

        merged.append(group)

    merged = pd.concat(merged, ignore_index=True)
    return merged.drop(columns="area")


def _province_display_name(row):
    for key in ("name_en", "name"):
        text = _clean_optional_text(row.get(key))
        if text:
            return text
    return ""


def _normalize_merge_name(value):
    text = _clean_optional_text(value)
    if not text:
        return ""

    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9]+", " ", text.lower())
    return text.strip()


def _first_non_empty(series):
    for value in series:
        text = _clean_optional_text(value)
        if text:
            return text
    return ""


def _prune_tiny_polygon_components(geom):
    if geom.is_empty or geom.geom_type != "MultiPolygon":
        return geom

    parts = [p for p in geom.geoms if not p.is_empty and float(p.area) > 0.0]
    if len(parts) <= 1:
        return geom

    largest_area = max(float(part.area) for part in parts)
    keep_parts = [
        part
        for part in parts
        if float(part.area) >= MIN_ISLET_COMPONENT_AREA_ABS
        or float(part.area) >= (largest_area * MIN_ISLET_COMPONENT_AREA_REL)
    ]

    if not keep_parts:
        keep_parts = [max(parts, key=lambda part: float(part.area))]

    if len(keep_parts) == len(parts):
        return geom

    return unary_union(keep_parts).buffer(0)


def prune_tiny_land_components(gdf):
    gdf = gdf.copy()
    removed_parts = 0

    new_geometry = []
    for geom in gdf.geometry:
        if geom.is_empty or geom.geom_type != "MultiPolygon":
            new_geometry.append(geom)
            continue

        parts_before = [p for p in geom.geoms if not p.is_empty and float(p.area) > 0.0]
        pruned = _prune_tiny_polygon_components(geom)
        parts_after = [p for p in getattr(pruned, "geoms", [pruned]) if not p.is_empty and float(p.area) > 0.0]
        removed_parts += max(0, len(parts_before) - len(parts_after))
        new_geometry.append(pruned)

    gdf["geometry"] = new_geometry
    gdf["geometry"] = gdf.geometry.buffer(0)
    debug(f"Tiny land components pruned: {removed_parts}")
    return gdf


def merge_same_name_provinces(gdf):
    gdf = gdf.copy()
    if "is_capital_province" not in gdf.columns:
        gdf["is_capital_province"] = 0
    if "capital_city_name" not in gdf.columns:
        gdf["capital_city_name"] = ""

    gdf["_merge_name_raw"] = gdf.apply(_province_display_name, axis=1)
    gdf["_merge_name_key"] = gdf["_merge_name_raw"].apply(_normalize_merge_name)
    gdf["_merge_area"] = gdf.geometry.area

    merged_rows = []
    merged_groups = 0
    removed_rows = 0

    for _, country_group in gdf.groupby("country", sort=False):
        for _, same_name in country_group.groupby("_merge_name_key", sort=False):
            key = same_name.iloc[0]["_merge_name_key"]
            if not key or len(same_name) == 1:
                for _, row in same_name.iterrows():
                    merged_rows.append(row.copy())
                continue

            merged_groups += 1
            removed_rows += len(same_name) - 1

            rep_idx = same_name["_merge_area"].idxmax()
            merged_row = same_name.loc[rep_idx].copy()
            merged_row["geometry"] = unary_union(list(same_name.geometry))
            merged_row["is_capital_province"] = int(
                same_name["is_capital_province"].fillna(0).astype(int).max()
            )

            cap_rows = same_name[same_name["is_capital_province"].fillna(0).astype(int) > 0]
            capital_city = _first_non_empty(cap_rows.get("capital_city_name", pd.Series(dtype=str)))
            if not capital_city:
                capital_city = _first_non_empty(same_name.get("capital_city_name", pd.Series(dtype=str)))
            merged_row["capital_city_name"] = capital_city

            for key_name in ("name_en", "name"):
                if key_name not in same_name.columns:
                    continue
                if _clean_optional_text(merged_row.get(key_name)):
                    continue
                merged_row[key_name] = _first_non_empty(same_name[key_name])

            merged_rows.append(merged_row)

    merged_df = gpd.GeoDataFrame(pd.DataFrame(merged_rows), geometry="geometry", crs=gdf.crs)
    merged_df = merged_df.drop(columns=["_merge_name_raw", "_merge_name_key", "_merge_area"], errors="ignore")
    merged_df = merged_df.reset_index(drop=True)

    debug(
        "Duplicate-name merge groups: "
        f"{merged_groups}, provinces merged away: {removed_rows}"
    )
    return merged_df


def _build_country_neighbor_map(country_group):
    idx_list = list(country_group.index)
    neighbors = {idx: set() for idx in idx_list}

    for i, left_idx in enumerate(idx_list):
        left_geom = country_group.loc[left_idx, "geometry"]
        if left_geom.is_empty:
            continue

        left_boundary = left_geom.boundary

        for right_idx in idx_list[i + 1:]:
            right_geom = country_group.loc[right_idx, "geometry"]
            if right_geom.is_empty:
                continue

            shared_boundary = left_boundary.intersection(right_geom.boundary)
            if shared_boundary.is_empty or float(shared_boundary.length) <= 0.0:
                # Hole removal can turn enclave boundaries into overlaps.
                # Treat positive-area overlap as adjacency for merge logic.
                overlap_area = float(left_geom.intersection(right_geom).area)
                if overlap_area <= 0.0:
                    continue

            neighbors[left_idx].add(right_idx)
            neighbors[right_idx].add(left_idx)

    return neighbors


def _build_all_neighbors_map(gdf):
    idx_list = list(gdf.index)
    neighbors = {idx: set() for idx in idx_list}

    for i, left_idx in enumerate(idx_list):
        left_geom = gdf.loc[left_idx, "geometry"]
        if left_geom.is_empty:
            continue

        left_boundary = left_geom.boundary

        for right_idx in idx_list[i + 1:]:
            right_geom = gdf.loc[right_idx, "geometry"]
            if right_geom.is_empty:
                continue

            shared_boundary = left_boundary.intersection(right_geom.boundary)
            if shared_boundary.is_empty or float(shared_boundary.length) <= 0.0:
                overlap_area = float(left_geom.intersection(right_geom).area)
                if overlap_area <= 0.0:
                    continue

            neighbors[left_idx].add(right_idx)
            neighbors[right_idx].add(left_idx)

    return neighbors


def _has_sea_neighbor(geom, land_union_boundary):
    if geom.is_empty:
        return False

    shared_with_sea = geom.boundary.intersection(land_union_boundary)
    if shared_with_sea.is_empty:
        return False
    return float(shared_with_sea.length) > 0.0


def _pick_best_merge_target(candidates, part_geom, require_touching=False):
    """Pick best target: touching first, then strongest shared boundary/overlap, then nearest."""
    best_idx = None
    best_key = None

    for cand_idx, cand_geom in candidates.items():
        if cand_geom.is_empty:
            continue

        shared_boundary = part_geom.boundary.intersection(cand_geom.boundary)
        shared_len = float(shared_boundary.length) if not shared_boundary.is_empty else 0.0
        overlap_area = float(part_geom.intersection(cand_geom).area)
        distance = float(part_geom.distance(cand_geom))

        touches = shared_len > 0.0 or overlap_area > 0.0
        if require_touching and not touches:
            continue

        key = (1 if touches else 0, shared_len, overlap_area, -distance)

        if best_key is None or key > best_key:
            best_key = key
            best_idx = cand_idx

    return best_idx


def merge_inland_disconnected_parts(gdf):
    """
    Merge inland disconnected fragments of a province into neighboring provinces
    of the same country. Sea-separated components (islands/coastal parts) are kept.

    Implementation note:
    Use a single pass over a snapshot of province indices to avoid oscillating
    re-merges (A -> B -> A) that can stall the pipeline.
    """
    gdf = gdf.copy()
    if "is_capital_province" not in gdf.columns:
        gdf["is_capital_province"] = 0
    if "capital_city_name" not in gdf.columns:
        gdf["capital_city_name"] = ""

    land_union_boundary = unary_union(gdf.geometry).boundary

    merged_groups = []
    moved_parts_count = 0
    dropped_provinces = 0
    skipped_no_touch_target = 0

    for _, country_group in gdf.groupby("country", sort=False):
        group = country_group.copy()

        # Snapshot only indices; geometry stays live so received parts are preserved.
        source_indices = list(group.index)
        for idx in source_indices:
            if idx not in group.index:
                continue

            geom = group.loc[idx, "geometry"]
            if geom.is_empty or geom.geom_type != "MultiPolygon":
                continue

            parts = [p for p in geom.geoms if not p.is_empty and float(p.area) > 0.0]
            if len(parts) <= 1:
                continue

            part_sea_flags = [(p, _has_sea_neighbor(p, land_union_boundary)) for p in parts]
            sea_parts = [p for p, is_sea in part_sea_flags if is_sea]
            inland_parts = [p for p, is_sea in part_sea_flags if not is_sea]

            if not inland_parts:
                continue

            keep_parts = list(sea_parts)
            move_parts = list(inland_parts)

            # If all parts are inland, keep the largest and merge the rest.
            if not keep_parts:
                main_part = max(parts, key=lambda p: float(p.area))
                keep_parts = [main_part]
                move_parts = [p for p in parts if p is not main_part]
                if not move_parts:
                    continue

            moved_any_part = False
            unmoved_parts = []
            for part in sorted(move_parts, key=lambda p: float(p.area), reverse=True):
                candidates = group.geometry.drop(idx, errors="ignore")
                if candidates.empty:
                    unmoved_parts.append(part)
                    break

                target_idx = _pick_best_merge_target(candidates, part, require_touching=True)
                if target_idx is None or target_idx not in group.index:
                    skipped_no_touch_target += 1
                    unmoved_parts.append(part)
                    continue

                target_geom = group.loc[target_idx, "geometry"]
                group.loc[target_idx, "geometry"] = target_geom.union(part).buffer(0)

                moved_parts_count += 1
                moved_any_part = True

            if not moved_any_part:
                continue

            # Keep any inland fragments that could not be reassigned safely.
            remaining_parts = keep_parts + unmoved_parts
            new_geom = unary_union(remaining_parts).buffer(0) if remaining_parts else Polygon()
            if new_geom.is_empty or float(new_geom.area) <= 0.0:
                if bool(group.loc[idx].get("is_capital_province", 0)):
                    recipients = group.geometry.drop(idx, errors="ignore")
                    if not recipients.empty:
                        receiver_idx = _pick_best_merge_target(recipients, geom)
                        if receiver_idx is None:
                            receiver_idx = recipients.index[0]
                        group.loc[receiver_idx, "is_capital_province"] = 1
                        if not _clean_optional_text(group.loc[receiver_idx].get("capital_city_name", "")):
                            group.loc[receiver_idx, "capital_city_name"] = _clean_optional_text(
                                group.loc[idx].get("capital_city_name", "")
                            )

                group = group.drop(idx)
                dropped_provinces += 1
            else:
                group.loc[idx, "geometry"] = new_geom

        merged_groups.append(group)

    merged_df = gpd.GeoDataFrame(
        pd.concat(merged_groups, ignore_index=True),
        geometry="geometry",
        crs=gdf.crs,
    )
    merged_df = merged_df.reset_index(drop=True)

    debug(
        "Inland disconnected-part merges applied: "
        f"{moved_parts_count}, provinces dropped: {dropped_provinces}, "
        f"skipped no-touch fragments: {skipped_no_touch_target}"
    )
    return merged_df


def merge_single_neighbor_provinces(gdf):
    gdf = gdf.copy()
    if "is_capital_province" not in gdf.columns:
        gdf["is_capital_province"] = 0
    if "capital_city_name" not in gdf.columns:
        gdf["capital_city_name"] = ""

    gdf["_merge_area"] = gdf.geometry.area
    land_union_boundary = unary_union(gdf.geometry).boundary
    global_neighbor_map = _build_all_neighbors_map(gdf)
    country_by_idx = gdf["country"].to_dict()

    merged_groups = []
    merged_count = 0
    skipped_border_count = 0
    skipped_sea_count = 0

    for country, country_group in gdf.groupby("country", sort=False):
        group = country_group.copy()

        while True:
            neighbor_map = _build_country_neighbor_map(group)
            leaves = [idx for idx, nbrs in neighbor_map.items() if len(nbrs) == 1]
            if not leaves:
                break

            leaves_sorted = sorted(
                leaves,
                key=lambda idx: (float(group.loc[idx, "_merge_area"]), int(idx)),
            )

            merged_this_round = False
            for idx in leaves_sorted:
                if idx not in group.index:
                    continue

                neighbors = [n for n in neighbor_map.get(idx, set()) if n in group.index]
                if len(neighbors) != 1:
                    continue

                neighbor_idx = neighbors[0]
                if neighbor_idx == idx:
                    continue

                # Sea counts as a neighbor for this rule, so coastal provinces
                # are not eligible for one-neighbor merge.
                if _has_sea_neighbor(group.loc[idx, "geometry"], land_union_boundary):
                    skipped_sea_count += 1
                    continue

                if idx not in global_neighbor_map or neighbor_idx not in global_neighbor_map:
                    continue

                foreign_neighbors = [
                    n
                    for n in global_neighbor_map.get(idx, set())
                    if n in global_neighbor_map and country_by_idx.get(n) != country
                ]
                if foreign_neighbors:
                    skipped_border_count += 1
                    continue

                current = group.loc[idx]
                neighbor = group.loc[neighbor_idx]

                merged_geom = current.geometry.union(neighbor.geometry)
                merged_capital_flag = int(
                    bool(current.get("is_capital_province", 0))
                    or bool(neighbor.get("is_capital_province", 0))
                )
                current_capital_city = _clean_optional_text(current.get("capital_city_name", ""))
                neighbor_capital_city = _clean_optional_text(neighbor.get("capital_city_name", ""))
                merged_capital_city = current_capital_city or neighbor_capital_city

                group.loc[idx, "geometry"] = merged_geom
                group.loc[idx, "is_capital_province"] = merged_capital_flag
                group.loc[idx, "capital_city_name"] = merged_capital_city

                for key_name in ("name_en", "name"):
                    if key_name not in group.columns:
                        continue
                    if _clean_optional_text(group.loc[idx].get(key_name)):
                        continue
                    group.loc[idx, key_name] = _clean_optional_text(neighbor.get(key_name))

                group.loc[idx, "_merge_area"] = merged_geom.area
                group = group.drop(neighbor_idx)

                idx_neighbors = set(global_neighbor_map.get(idx, set()))
                removed_neighbors = set(global_neighbor_map.get(neighbor_idx, set()))
                combined_neighbors = (idx_neighbors | removed_neighbors) - {idx, neighbor_idx}

                for other_idx in combined_neighbors:
                    if other_idx not in global_neighbor_map:
                        continue
                    global_neighbor_map[other_idx].discard(neighbor_idx)
                    global_neighbor_map[other_idx].add(idx)

                global_neighbor_map[idx] = combined_neighbors
                del global_neighbor_map[neighbor_idx]

                merged_count += 1
                merged_this_round = True
                break

            if not merged_this_round:
                break

        merged_groups.append(group)

    merged_df = gpd.GeoDataFrame(
        pd.concat(merged_groups, ignore_index=True),
        geometry="geometry",
        crs=gdf.crs,
    )
    merged_df = merged_df.drop(columns=["_merge_area"], errors="ignore")
    merged_df = merged_df.reset_index(drop=True)
    debug(
        "Single-neighbor merges applied: "
        f"{merged_count}, skipped border candidates: {skipped_border_count}, "
        f"skipped sea candidates: {skipped_sea_count}"
    )
    return merged_df


# Apply merge
land = merge_small_absolute(land)

debug("PART 2.6 START — merging same-name provinces...")
before_same_name_merge = len(land)
land = merge_same_name_provinces(land)
debug(
    "PART 2.6 DONE — duplicate-name merged provinces removed: "
    f"{before_same_name_merge - len(land)}"
)

if ENABLE_INLAND_DISCONNECTED_MERGE:
    debug("PART 2.65 START — merging inland disconnected parts...")
    before_disconnected_merge = len(land)
    land = merge_inland_disconnected_parts(land)
    debug(
        "PART 2.65 DONE — disconnected-part merged provinces removed: "
        f"{before_disconnected_merge - len(land)}"
    )
else:
    debug("PART 2.65 SKIPPED — inland disconnected merge disabled")

debug("PART 2.7 START — merging one-neighbor provinces...")
before_single_neighbor_merge = len(land)
land = merge_single_neighbor_provinces(land)
debug(
    "PART 2.7 DONE — one-neighbor merged provinces removed: "
    f"{before_single_neighbor_merge - len(land)}"
)

debug("PART 2.8 START — pruning tiny disconnected land components...")
land = prune_tiny_land_components(land)
debug("PART 2.8 DONE")

land_union = unary_union(land.geometry)

debug(f"PART 2.5 DONE ")

# =====================================================================
# PART 3 — SEA REGIONS
# =====================================================================
debug("After merge small: " + str(len(land)))

debug("PART 3 START — generating sea regions")

# Keep map bounds anchored to the base Europe footprint.
# The custom AEO province is decorative and should not expand sea extent.
bounds_land = land
if "country" in land.columns:
    base_land = land[land["country"] != CUSTOM_ISLAND_COUNTRY]
    if len(base_land) > 0:
        bounds_land = base_land

minx, miny, maxx, maxy = bounds_land.total_bounds

outer = box(minx - 100000, miny - 100000, maxx + 100000, maxy + 100000)
sea = outer.difference(land_union)

# Remove accidental inland sea pockets in selected landlocked countries.
if "country" in land.columns:
    inland_mask = land[land["country"].isin(INLAND_NO_SEA_COUNTRIES)]
    if len(inland_mask) > 0:
        inland_union = unary_union(inland_mask.geometry)
        if not inland_union.is_empty:
            sea = sea.difference(inland_union.buffer(INLAND_NO_SEA_BUFFER_M))

# Generate sea regions using Voronoi diagram per connected sea component.
# This prevents one sea province from spanning disconnected basins
# (which can create unrealistic neighbor lists).
final_regions = []

debug("Generating sea regions using component-aware Voronoi diagram...")

if sea.geom_type == "Polygon":
    sea_components = [sea]
elif sea.geom_type == "MultiPolygon":
    sea_components = list(sea.geoms)
else:
    sea_components = [g for g in getattr(sea, "geoms", []) if g.geom_type == "Polygon"]

sea_components = [p for p in sea_components if not p.is_empty and float(p.area) > 0.0]

from sklearn.cluster import KMeans

TARGET_SEA_REGIONS = 120
component_count = len(sea_components)
target_regions = max(TARGET_SEA_REGIONS, component_count)

if component_count == 0:
    debug("No sea components found after clipping.")
else:
    areas = np.array([float(p.area) for p in sea_components], dtype=float)
    area_sum = float(areas.sum())
    if area_sum <= 0.0:
        region_alloc = np.ones(component_count, dtype=int)
    else:
        # Ensure at least one region per connected sea component.
        region_alloc = np.ones(component_count, dtype=int)
        remaining = target_regions - component_count
        if remaining > 0:
            raw = (areas / area_sum) * remaining
            extra = np.floor(raw).astype(int)
            region_alloc += extra
            leftover = int(remaining - int(extra.sum()))
            if leftover > 0:
                fractions = raw - extra
                order = np.argsort(fractions)[::-1]
                for idx in order[:leftover]:
                    region_alloc[idx] += 1

    total_points = 0

    for comp_idx, (component, comp_regions) in enumerate(zip(sea_components, region_alloc), start=1):
        comp_regions = max(1, int(comp_regions))

        if comp_regions == 1:
            clipped = component
            try:
                clipped = clipped.buffer(15000).buffer(-15000)
            except Exception:
                pass
            if not clipped.is_empty and float(clipped.area) > 0.0:
                final_regions.append(clipped)
            continue

        cminx, cminy, cmaxx, cmaxy = component.bounds
        target_points_for_component = max(400, comp_regions * 180)
        max_attempts = target_points_for_component * 12

        points = []
        for _ in range(max_attempts):
            if len(points) >= target_points_for_component:
                break
            x = np.random.uniform(cminx, cmaxx)
            y = np.random.uniform(cminy, cmaxy)
            p = Point(x, y)
            if component.contains(p):
                points.append([x, y])

        if len(points) < comp_regions:
            rp = component.representative_point()
            while len(points) < comp_regions:
                points.append([float(rp.x), float(rp.y)])

        points = np.array(points, dtype=float)
        n_clusters = min(comp_regions, len(points))
        if n_clusters <= 0:
            continue

        total_points += int(len(points))

        kmeans = KMeans(n_clusters=n_clusters, n_init="auto")
        centers = kmeans.fit(points).cluster_centers_

        vor = voronoi_diagram(MultiPoint([Point(c[0], c[1]) for c in centers]))

        for poly in vor.geoms:
            clipped = poly.intersection(component)
            if clipped.is_empty:
                continue

            try:
                clipped = clipped.buffer(15000).buffer(-15000)
            except Exception:
                pass

            if not clipped.is_empty and float(clipped.area) > 0.0:
                final_regions.append(clipped)

    debug(
        "Sea Voronoi components: "
        f"{component_count}, sampled points: {total_points}, "
        f"target regions: {target_regions}"
    )

debug(f"Sea regions generated: {len(final_regions)}")
debug("PART 3 DONE")


# =====================================================================
# PART 4 — PREVIEW
# =====================================================================

debug("PART 4 START — generating preview image")

fig, ax = plt.subplots(figsize=(18, 12))

# sea
for region in final_regions:
    color = (random.random(), random.random(), random.random(), 0.7)
    if region.geom_type == "MultiPolygon":
        for p in region.geoms:
            xs, ys = p.exterior.xy
            ax.fill(xs, ys, color=color)
    else:
        xs, ys = region.exterior.xy
        ax.fill(xs, ys, color=color)

# land borders
land.boundary.plot(ax=ax, color="white", linewidth=0.6)

ax.set_axis_off()
fig.savefig(os.path.join(BASE, "preview_map.png"), dpi=350)
plt.close(fig)

debug("PART 4 DONE")


# =====================================================================
# PART 5 — EXPORT TO OPENGS
# =====================================================================

debug("Starting export...")

from export_to_opengs import run_export

# předá provinces + voronoi sea regions
run_export(land, final_regions)



debug("Export complete.")
