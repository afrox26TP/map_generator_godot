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

    # -------------------------
    # SEA REGIONS (unique too)
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

    id_map = np.zeros((h, w), dtype=np.int32)

    for y in range(h):
        for x in range(w):
            r, g, b = arr[y, x]
            id_map[y, x] = lut[r, g, b]

    max_pid = int(id_map.max())
    if max_pid > 0xFFFFFF:
        raise ValueError(
            f"Province ID {max_pid} cannot be represented in 24-bit RGB mask."
        )

    # ID mask output (RGB encodes province ID directly).
    id_mask = Image.new("RGB", (w, h))
    px = id_mask.load()

    for y in range(h):
        for x in range(w):
            pid = id_map[y, x]
            if pid < 0:
                px[x, y] = SEA_COLOR
            else:
                px[x, y] = encode_province_id_rgb(pid)

    id_mask.save(os.path.join(OUT, "ProvinceIDMask.png"))
    # Backward-compatible alias used by existing runtime tools.
    id_mask.save(os.path.join(OUT, "ProvinceMask.png"))
    return id_map


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


def export_provinces_txt(province_colors, id_map, land, population_rows=None, gdp_rows=None):

    out_path = os.path.join(OUT, "Provinces.txt")
    h, w = id_map.shape

    pid_to_color = {pid: col for col, pid in province_colors.items()}
    population_by_pid = _build_population_export_lookup(population_rows)
    gdp_by_pid = _build_gdp_export_lookup(gdp_rows)
    rows = []

    max_pid = int(id_map.max())

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

        ys, xs = np.where(id_map == pid)
        if len(xs) == 0:
            cx, cy = 0, 0
        else:
            cx = int(xs.mean())
            cy = int(ys.mean())

        rows.append(
            f"{pid};{r};{g};{b};{typ};{st};{owner};{controller};{cx};{cy};"
            f"{province_name};{country_name};{population};{gdp_value:.2f};{gdp_per_capita:.6f}"
        )

    # SEA detection
    used_colors = set(pid_to_color.values())
    img = Image.open(os.path.join(OUT, "ProvinceMap.png")).convert("RGB")
    arr = np.array(img)

    sea_seen = {}
    for y in range(arr.shape[0]):
        for x in range(arr.shape[1]):
            col = tuple(arr[y, x])
            if col not in used_colors:
                if col not in sea_seen:
                    sea_seen[col] = len(sea_seen)

    base_sea_id = max_pid + 1
    for idx, (col, _) in enumerate(sea_seen.items()):
        r, g, b = col
        sea_id = base_sea_id + idx
        rows.append(
            f"{sea_id};{r};{g};{b};sea;SEA;SEA;SEA;0;0;"
            f";SEA;0;0.00;0.000000"
        )

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(
            "id;R;G;B;type;state;owner;controller;x;y;"
            "province_name;country_name;population;gdp;gdp_per_capita\n"
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
    id_map = export_id_map(province_colors)

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
            print(f" - {name} ({country})")
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

    print("[EXPORT] Provinces.txt...")
    export_provinces_txt(
        province_colors,
        id_map,
        land,
        population_rows=rows,
        gdp_rows=gdp_rows,
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
    export_ideology_map(id_map, sea_regions, bounds, max_pid=max_pid)

    export_states(land)
    export_state_files(land)

    print("[EXPORT] EXPORT COMPLETE")
