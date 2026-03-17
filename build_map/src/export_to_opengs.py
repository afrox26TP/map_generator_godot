import json
import os
import random
import numpy as np
from PIL import Image, ImageDraw

from export_shared import EXPORT_SIZE, SEA_COLOR, OUT, geom_to_pixel_coords
from export_political_map import export_political_map
from export_theme_map import (
    export_gdp_map,
    export_population_map,
    export_ideology_map,
)
from import_population import generate_population_dataset
from import_gdp import generate_gdp_dataset
from import_ideology import generate_ideology_dataset


# --------------------------------------------------------
# UNIQUE COLOR GENERATOR (no duplication possible)
# --------------------------------------------------------
def unique_color(used, step=16):
    while True:
        step = 20   # increase to 32 if needed

        r = random.randrange(0, 256, step)
        g = random.randrange(0, 256, step)
        b = random.randrange(0, 256, step)

        c = (r, g, b)
        if c not in used:
            used.add(c)
            return c

# --------------------------------------------------------
# EXPORT PROVINCE MAP (colors must NOT repeat)
# --------------------------------------------------------
def export_province_map(land, sea_regions):

    minx, miny, maxx, maxy = land.total_bounds
    bounds = (minx, miny, maxx, maxy)

    img = Image.new("RGB", (EXPORT_SIZE, EXPORT_SIZE), SEA_COLOR)
    draw = ImageDraw.Draw(img)

    province_colors = {}
    used_colors = set()   # stores all used RGB colors

    # -------------------------
    # SEA REGIONS (unique too)
    # Draw sea first so later land fills restore islands even when
    # the rasterized sea polygon ignores interior holes.
    # -------------------------
    sea_color_count = 0

    for region in sea_regions:
        color = unique_color(used_colors)
        sea_color_count += 1

        polys = [region] if region.geom_type == "Polygon" else region.geoms
        for poly in polys:
            coords = geom_to_pixel_coords(poly, bounds, EXPORT_SIZE)
            draw.polygon(coords, fill=color)

    print("[DEBUG] Sea regions:", sea_color_count)

    # -------------------------
    # LAND PROVINCES
    # -------------------------
    for pid, row in land.iterrows():
        geom = row.geometry
        if geom.is_empty:
            continue

        color = unique_color(used_colors)
        province_colors[color] = pid

        polys = [geom] if geom.geom_type == "Polygon" else geom.geoms
        for poly in polys:
            coords = geom_to_pixel_coords(poly, bounds, EXPORT_SIZE)
            draw.polygon(coords, fill=color)

    print("[DEBUG] Land provinces:", len(land))
    print("[DEBUG] Unique land colors:", len(province_colors))
    print("[DEBUG] Total unique colors:", len(used_colors))

    # -------------------------
    # SAVE UNCOMPRESSED PNG
    # -------------------------
    img.save(
        os.path.join(OUT, "ProvinceMap.png"),
        format="PNG",
        optimize=False,
        compress_level=0,
        bits=8
    )

    return province_colors, bounds


# --------------------------------------------------------
# EXPORT ID MAP
# --------------------------------------------------------
def encode_province_id_rgb(pid):
    pid_i = int(pid)
    if pid_i < 0:
        raise ValueError("Province ID must be non-negative.")
    if pid_i > 0xFFFFFF:
        raise ValueError("Province ID exceeds 24-bit RGB encoding limit (16777215).")

    return (
        pid_i & 0xFF,
        (pid_i >> 8) & 0xFF,
        (pid_i >> 16) & 0xFF,
    )


def export_id_map(province_colors):

    img = Image.open(os.path.join(OUT, "ProvinceMap.png")).convert("RGB")
    arr = np.array(img)
    h, w, _ = arr.shape

    lut = np.full((256, 256, 256), -1, dtype=np.int32)

    for col, pid in province_colors.items():
        r, g, b = col
        lut[r, g, b] = pid

    id_map = np.full((h, w), -1, dtype=np.int32)
    sea_colors_in_order = []
    sea_seen = set()

    for y in range(h):
        for x in range(w):
            r, g, b = arr[y, x]
            pid = lut[r, g, b]
            id_map[y, x] = pid
            if pid < 0:
                col = (int(r), int(g), int(b))
                if col not in sea_seen:
                    sea_seen.add(col)
                    sea_colors_in_order.append(col)

    max_pid = int(id_map.max())
    base_sea_id = max_pid + 1
    sea_color_to_id = {
        col: base_sea_id + idx
        for idx, col in enumerate(sea_colors_in_order)
    }

    max_encoded_id = max(
        max_pid,
        max(sea_color_to_id.values()) if sea_color_to_id else -1,
    )
    if max_encoded_id > 0xFFFFFF:
        raise ValueError(
            f"Province ID {max_encoded_id} cannot be represented in 24-bit RGB mask."
        )

    # ID mask output (RGB encodes province ID directly).
    id_mask = Image.new("RGB", (w, h))
    px = id_mask.load()

    for y in range(h):
        for x in range(w):
            pid = id_map[y, x]
            if pid < 0:
                col = tuple(int(v) for v in arr[y, x])
                px[x, y] = encode_province_id_rgb(sea_color_to_id[col])
            else:
                px[x, y] = encode_province_id_rgb(pid)

    id_mask.save(os.path.join(OUT, "ProvinceIDMask.png"))
    # Backward-compatible alias used by existing runtime tools.
    id_mask.save(os.path.join(OUT, "ProvinceMask.png"))
    return id_map, sea_color_to_id


# --------------------------------------------------------
# EXPORT STATES
# --------------------------------------------------------
def export_states(land):
    states = sorted(land["country"].unique())

    with open(os.path.join(OUT, "States.txt"), "w") as f:
        for st in states:
            r = random.randint(20, 235)
            g = random.randint(20, 235)
            b = random.randint(20, 235)
            f.write(f"{st};{r};{g};{b}\n")


# --------------------------------------------------------
# EXPORT STATE FILES
# --------------------------------------------------------
def export_state_files(land):
    folder = os.path.join(OUT, "States")
    states = sorted(land["country"].unique())
    sid = 1

    for st in states:
        provs = land.index[land["country"] == st].tolist()

        with open(os.path.join(folder, f"{sid}_{st}.txt"), "w") as f:
            f.write("state={\n")
            f.write(f"    id={sid}\n")
            f.write(f"    name=\"STATE_{st}\"\n")
            f.write("    provinces={\n")
            for p in provs:
                f.write(f"        {p}\n")
            f.write("    }\n")
            f.write("}\n")

        sid += 1


# --------------------------------------------------------
# EXPORT PROVINCES.TXT
# --------------------------------------------------------
def _sanitize_txt_field(value):
    text = "" if value is None else str(value)
    return text.replace(";", ",").replace("\r", " ").replace("\n", " ").strip()


def _normalize_flag(value):
    if value is None:
        return 0
    if isinstance(value, (bool, np.bool_)):
        return int(value)
    if isinstance(value, (int, np.integer)):
        return 1 if int(value) != 0 else 0
    if isinstance(value, (float, np.floating)):
        return 1 if float(value) > 0 else 0

    text = str(value).strip().lower()
    if text in {"", "none", "nan", "-99", "0", "false", "no"}:
        return 0
    if text in {"1", "true", "yes"}:
        return 1

    try:
        return 1 if float(text) > 0 else 0
    except ValueError:
        return 0


def _clean_optional_text(value):
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"", "none", "nan"}:
        return ""
    return text


def _city_from_woe_label(value):
    text = _clean_optional_text(value)
    if not text:
        return ""
    return text.split(",", 1)[0].strip()


def _row_is_capital(land_row):
    explicit_flag = _normalize_flag(land_row.get("is_capital_province", 0))
    if explicit_flag:
        return 1

    for key in ("type_en", "type"):
        text = str(land_row.get(key) or "")
        if "capital" in text.lower():
            return 1

    return 0


def _build_country_capital_lookup(land):
    lookup = {}

    for _, row in land.iterrows():
        type_en = str(row.get("type_en") or "")
        type_raw = str(row.get("type") or "")
        if "capital" not in type_en.lower() and "capital" not in type_raw.lower():
            continue

        country = _clean_optional_text(row.get("country"))
        if not country or country in lookup:
            continue

        for key in ("capital_city_name", "woe_name"):
            city = _clean_optional_text(row.get(key))
            if city:
                lookup[country] = city
                break

        if country in lookup:
            continue

        city = _city_from_woe_label(row.get("woe_label"))
        if city:
            lookup[country] = city

    return lookup


def _row_capital_city_name(land_row, country_capitals):
    city = _clean_optional_text(land_row.get("capital_city_name"))
    if city:
        return city

    country = _clean_optional_text(land_row.get("country"))
    if country:
        city = _clean_optional_text(country_capitals.get(country))
        if city:
            return city

    for key in ("woe_name",):
        city = _clean_optional_text(land_row.get(key))
        if city:
            return city

    city = _city_from_woe_label(land_row.get("woe_label"))
    if city:
        return city

    for key in ("name_en", "name"):
        city = _clean_optional_text(land_row.get(key))
        if city:
            return city

    return ""


def _build_population_export_lookup(rows):
    lookup = {}
    for row in rows or []:
        pid = int(row.get("province_id") or 0)
        lookup[pid] = {
            "country_name": _sanitize_txt_field(row.get("country") or row.get("country_name") or ""),
            "population": int(row.get("population") or 0),
        }
    return lookup


def _build_gdp_export_lookup(rows):
    lookup = {}
    for row in rows or []:
        pid = int(row.get("province_id") or 0)
        lookup[pid] = {
            "gdp": float(row.get("gdp") or 0.0),
            "gdp_per_capita": float(row.get("gdp_per_capita") or 0.0),
        }
    return lookup


def _rgb_tuple_to_key(color):
    r, g, b = color
    return int(r) | (int(g) << 8) | (int(b) << 16)


def _build_full_id_map_with_sea(id_map, province_rgb_map, sea_color_to_id):
    """Return an ID map where sea pixels are replaced by stable sea IDs."""
    full_map = id_map.astype(np.int32, copy=True)
    if not sea_color_to_id:
        return full_map

    sea_mask = full_map < 0
    if not np.any(sea_mask):
        return full_map

    key_to_id = {
        _rgb_tuple_to_key(color): int(sea_id)
        for color, sea_id in sea_color_to_id.items()
    }
    if not key_to_id:
        return full_map

    map_keys = np.array(sorted(key_to_id.keys()), dtype=np.int64)
    map_vals = np.array([key_to_id[k] for k in map_keys], dtype=np.int32)

    flat_full = full_map.reshape(-1)
    flat_sea_mask = sea_mask.reshape(-1)
    sea_indices = np.flatnonzero(flat_sea_mask)
    if sea_indices.size == 0:
        return full_map

    color_keys = (
        province_rgb_map[..., 0].astype(np.int64)
        | (province_rgb_map[..., 1].astype(np.int64) << 8)
        | (province_rgb_map[..., 2].astype(np.int64) << 16)
    )
    sea_keys = color_keys.reshape(-1)[sea_indices]

    idx = np.searchsorted(map_keys, sea_keys)
    in_range = idx < map_keys.size
    if np.any(in_range):
        in_range_idx = idx[in_range]
        matched = map_keys[in_range_idx] == sea_keys[in_range]
        if np.any(matched):
            target_indices = sea_indices[in_range][matched]
            flat_full[target_indices] = map_vals[in_range_idx[matched]]

    return full_map


def _build_neighbor_lookup(full_id_map):
    """Build undirected province adjacency from a full ID map."""
    neighbors = {}

    def register_pairs(a, b):
        diff = a != b
        if not np.any(diff):
            return

        left = a[diff].astype(np.int64)
        right = b[diff].astype(np.int64)
        valid = (left >= 0) & (right >= 0)
        if not np.any(valid):
            return

        left = left[valid]
        right = right[valid]
        p_min = np.minimum(left, right)
        p_max = np.maximum(left, right)
        pairs = np.unique(np.column_stack((p_min, p_max)), axis=0)

        for p1, p2 in pairs:
            i1 = int(p1)
            i2 = int(p2)
            neighbors.setdefault(i1, set()).add(i2)
            neighbors.setdefault(i2, set()).add(i1)

    register_pairs(full_id_map[:, :-1], full_id_map[:, 1:])
    register_pairs(full_id_map[:-1, :], full_id_map[1:, :])
    return {pid: sorted(ids) for pid, ids in neighbors.items()}


def export_provinces_txt(
    province_colors,
    id_map,
    land,
    population_rows=None,
    gdp_rows=None,
    sea_color_to_id=None,
    ideology_rows=None,
):

    out_path = os.path.join(OUT, "Provinces.txt")
    h, w = id_map.shape

    pid_to_color = {pid: col for col, pid in province_colors.items()}
    population_by_pid = _build_population_export_lookup(population_rows)
    gdp_by_pid = _build_gdp_export_lookup(gdp_rows)
    ideology_by_pid = {
        int(r["province_id"]): str(r.get("ideology") or "unknown")
        for r in (ideology_rows or [])
    }
    rows = []
    country_capitals = _build_country_capital_lookup(land)

    max_pid = int(id_map.max())

    # SEA detection
    used_colors = set(pid_to_color.values())
    img = Image.open(os.path.join(OUT, "ProvinceMap.png")).convert("RGB")
    arr = np.array(img)

    if sea_color_to_id is None:
        sea_seen = {}
        for y in range(arr.shape[0]):
            for x in range(arr.shape[1]):
                col = tuple(int(v) for v in arr[y, x])
                if col not in used_colors and col not in sea_seen:
                    sea_seen[col] = len(sea_seen)

        base_sea_id = max_pid + 1
        sea_items = [
            (col, base_sea_id + idx)
            for idx, col in enumerate(sea_seen.keys())
        ]
    else:
        sea_items = sorted(sea_color_to_id.items(), key=lambda item: item[1])

    resolved_sea_color_to_id = {
        tuple(int(v) for v in col): int(sea_id)
        for col, sea_id in sea_items
    }
    full_id_map = _build_full_id_map_with_sea(id_map, arr, resolved_sea_color_to_id)
    neighbors_by_pid = _build_neighbor_lookup(full_id_map)

    for pid in range(max_pid + 1):
        if pid in pid_to_color:
            r, g, b = pid_to_color[pid]
            land_row = land.loc[pid]
            st = land_row["country"]
            typ = "land"
            owner = st
            controller = st
        else:
            continue

        province_name = _sanitize_txt_field(land_row.get("name_en") or land_row.get("name") or "")
        population_entry = population_by_pid.get(pid, {})
        gdp_entry = gdp_by_pid.get(pid, {})
        country_name = population_entry.get("country_name") or _sanitize_txt_field(land_row.get("admin") or st)
        population = int(population_entry.get("population") or 0)
        gdp_value = float(gdp_entry.get("gdp") or 0.0)
        gdp_per_capita = float(gdp_entry.get("gdp_per_capita") or 0.0)
        is_capital = _row_is_capital(land_row)
        capital_city = ""
        if is_capital:
            capital_city = _sanitize_txt_field(_row_capital_city_name(land_row, country_capitals))
        neighbor_ids = ",".join(str(n) for n in neighbors_by_pid.get(int(pid), []))
        ideology = ideology_by_pid.get(int(pid), "unknown")

        ys, xs = np.where(id_map == pid)
        if len(xs) == 0:
            cx, cy = 0, 0
        else:
            cx = int(xs.mean())
            cy = int(ys.mean())

        rows.append(
            f"{pid};{r};{g};{b};{typ};{st};{owner};{controller};{cx};{cy};"
            f"{province_name};{country_name};{population};{gdp_value:.2f};{gdp_per_capita:.6f};"
            f"{is_capital};{capital_city};{neighbor_ids};{ideology}"
        )

    for col, sea_id in sea_items:
        r, g, b = col
        neighbor_ids = ",".join(str(n) for n in neighbors_by_pid.get(int(sea_id), []))
        rows.append(
            f"{sea_id};{r};{g};{b};sea;SEA;SEA;SEA;0;0;"
            f";SEA;0;0.00;0.000000;0;;{neighbor_ids};unknown"
        )

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(
            "id;R;G;B;type;state;owner;controller;x;y;"
            "province_name;country_name;population;gdp;gdp_per_capita;"
            "is_capital;capital_city;neighbors;ideology\n"
        )
        for r in rows:
            f.write(r + "\n")

    print(f"[EXPORT] Provinces.txt written ({len(rows)} entries).")


def write_population_txt(rows, debug_rows, path):
    debug_map = {r["province_id"]: r for r in debug_rows}
    with open(path, "w", encoding="utf-8") as f:
        f.write("id;population;population_source;population_date;source_region;source_country;match_method\n")
        for r in rows:
            pid = r["province_id"]
            pop = r["population"] if r["population"] != "" else 0
            pop_date = r.get("population_date", "")
            source = r.get("population_source", "")
            d = debug_map.get(pid, {})
            f.write(
                f"{pid};{pop};{source};{pop_date};"
                f"{d.get('source_region','')};{d.get('source_country','')};{d.get('match_method','')}\n"
            )


def write_gdp_txt(rows, path):
    with open(path, "w", encoding="utf-8") as f:
        f.write("id;gdp;gdp_per_capita;gdp_source;gdp_year\n")
        for r in rows:
            pid = int(r.get("province_id") or 0)
            gdp_val = float(r.get("gdp") or 0.0)
            gdp_pc = float(r.get("gdp_per_capita") or 0.0)
            source = str(r.get("gdp_source") or "")
            year = r.get("gdp_year") or ""
            f.write(f"{pid};{gdp_val:.2f};{gdp_pc:.6f};{source};{year}\n")


def write_ideology_txt(rows, path):
    with open(path, "w", encoding="utf-8") as f:
        f.write("id;ideology;ideology_source;ideology_year\n")
        for r in rows:
            pid = int(r.get("province_id") or 0)
            ideology = str(r.get("ideology") or "unknown")
            source = str(r.get("ideology_source") or "")
            year = r.get("ideology_year") or ""
            f.write(f"{pid};{ideology};{source};{year}\n")


def export_population_lookup_json(land, province_colors, rows, path):
    """
    Export a Godot-ready lookup file:
    - by_id: province id -> population + metadata
    - by_color: "R,G,B" -> province id
    """
    rows_by_pid = {
        int(r["province_id"]): r
        for r in rows
    }
    pid_to_color = {pid: col for col, pid in province_colors.items()}

    by_id = {}
    by_color = {}

    for pid, land_row in land.iterrows():
        pid_i = int(pid)
        pop_row = rows_by_pid.get(pid_i, {})
        r, g, b = pid_to_color.get(pid_i, (0, 0, 0))

        by_id[str(pid_i)] = {
            "province_id": pid_i,
            "province_name": str(land_row.get("name_en") or land_row.get("name") or ""),
            "country_iso3": str(land_row.get("country") or ""),
            "country_name": str(land_row.get("admin") or land_row.get("country") or ""),
            "population": int(pop_row.get("population") or 0),
            "population_source": str(pop_row.get("population_source") or ""),
            "population_date": str(pop_row.get("population_date") or ""),
            "color_rgb": [int(r), int(g), int(b)],
            "color_hex": f"#{int(r):02X}{int(g):02X}{int(b):02X}",
        }
        by_color[f"{int(r)},{int(g)},{int(b)}"] = pid_i

    payload = {
        "version": 1,
        "by_id": by_id,
        "by_color": by_color,
    }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    print(f"[EXPORT] ProvincePopulationLookup.json written ({len(by_id)} land provinces).")


# --------------------------------------------------------
# MAIN EXPORT
# --------------------------------------------------------
def run_export(land, sea_regions):
    print("[EXPORT] ProvinceMap...")
    province_colors, bounds = export_province_map(land, sea_regions)

    print("[EXPORT] ProvinceIDMask...")
    id_map, sea_color_to_id = export_id_map(province_colors)

    print("[EXPORT] PoliticalMap...")
    export_political_map(id_map, land, sea_regions, bounds)

    max_pid = int(id_map.max())
    print(f"[DEBUG] MAX PID DETECTED = {max_pid}")

    print("[EXPORT] Population CSV + map colors...")
    pop_values, rows, unmatched, debug_rows = generate_population_dataset(
        land,
        out_path=os.path.join(OUT, "Population.csv"),
        debug_path=os.path.join(OUT, "Population_debug.csv"),
    )
    if unmatched:
        print(f"[WARN] Population unmatched regions: {len(unmatched)} (showing up to 5)")
        for name, country in unmatched[:5]:
            safe_name = str(name).encode("ascii", "replace").decode("ascii")
            safe_country = str(country).encode("ascii", "replace").decode("ascii")
            print(f" - {safe_name} ({safe_country})")
    write_population_txt(rows, debug_rows, os.path.join(OUT, "Population.txt"))
    export_population_lookup_json(
        land,
        province_colors,
        rows,
        os.path.join(OUT, "ProvincePopulationLookup.json"),
    )

    pop_source_by_pid = {
        r["province_id"]: r.get("population_source", "")
        for r in rows
    }
    pop_country_by_pid = {
        r["province_id"]: r.get("country", "")
        for r in rows
    }

    land_areas = {
        pid: land.loc[pid].geometry.area / 1_000_000
        for pid in land.index
        if land.loc[pid].geometry.area > 0
    }

    print("[EXPORT] GDP CSV + map colors...")
    gdp_values, gdp_rows, gdp_missing = generate_gdp_dataset(
        land,
        population=pop_values,
        out_path=os.path.join(OUT, "GDP.csv"),
    )
    write_gdp_txt(gdp_rows, os.path.join(OUT, "GDP.txt"))
    if gdp_missing:
        print(f"[WARN] GDP missing for {len(gdp_missing)} countries (GDP set to 0 there).")

    print("[EXPORT] Ideology CSV + map colors...")
    ideology_values, ideology_rows, ideology_missing = generate_ideology_dataset(
        land,
        out_path=os.path.join(OUT, "Ideology.csv"),
    )
    write_ideology_txt(ideology_rows, os.path.join(OUT, "Ideology.txt"))
    if ideology_missing:
        print(
            f"[WARN] Ideology missing for {len(ideology_missing)} countries "
            "(set to unknown there)."
        )

    print("[EXPORT] Provinces.txt...")
    export_provinces_txt(
        province_colors,
        id_map,
        land,
        population_rows=rows,
        gdp_rows=gdp_rows,
        sea_color_to_id=sea_color_to_id,
        ideology_rows=ideology_rows,
    )

    print("[EXPORT] GDP Map...")
    export_gdp_map(id_map, sea_regions, bounds, gdp=gdp_values, max_pid=max_pid)

    print("[EXPORT] Population Map...")
    export_population_map(
        id_map,
        sea_regions,
        bounds,
        population=pop_values,
        land_areas=land_areas,
        population_source=pop_source_by_pid,
        province_country=pop_country_by_pid,
        max_pid=max_pid,
    )

    print("[EXPORT] Ideology Map...")
    export_ideology_map(
        id_map,
        sea_regions,
        bounds,
        ideology_by_pid=ideology_values,
        max_pid=max_pid,
    )

    export_states(land)
    export_state_files(land)

    print("[EXPORT] EXPORT COMPLETE")
