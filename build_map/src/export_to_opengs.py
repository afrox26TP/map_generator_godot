import os
import json
import random
import numpy as np
import geopandas as gpd
import pandas as pd
from PIL import Image, ImageDraw

# ===============================================================
# CONFIG
# ===============================================================

EXPORT_SIZE = 4096
SEA_COLOR = (20, 80, 200)           # jednotná modrá pro všechny mapy krom ProvinceMap
OUTLINE_COLOR = (0, 32, 96)         # #002060 – outline voronoi hranic
OUTLINE_WIDTH = 1

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "opengs_export")

os.makedirs(OUT, exist_ok=True)
os.makedirs(os.path.join(OUT, "States"), exist_ok=True)


# ===============================================================
# RASTER HELPER: Convert geometry → pixel polygon
# ===============================================================

def geom_to_pixel_coords(geom, bounds, size):
    minx, miny, maxx, maxy = bounds
    w = size
    h = size

    coords = []
    for x, y in geom.exterior.coords:
        px = int((x - minx) / (maxx - minx) * w)
        py = int((1 - (y - miny) / (maxy - miny)) * h)
        coords.append((px, py))

    return coords


# ===============================================================
# EXPORT 1 — PROVINCE MAP (WITH FULL VORONOI SEA REGIONS)
# ===============================================================

def export_province_map(land, sea_regions):
    """
    ProvinceMap.png
    - Provinces: random unique colors
    - Sea: Voronoi regions, each with random color
    - IMPORTANT: Sea regions are NOT added to province_colors → NO ID
    """

    minx, miny, maxx, maxy = land.total_bounds
    bounds = (minx, miny, maxx, maxy)

    img = Image.new("RGB", (EXPORT_SIZE, EXPORT_SIZE), SEA_COLOR)
    draw = ImageDraw.Draw(img)

    province_colors = {}

    # ---------------------------
    # LAND PROVINCES
    # ---------------------------
    for pid, row in land.iterrows():
        geom = row.geometry
        if geom.is_empty:
            continue

        color = (
            random.randint(20, 235),
            random.randint(20, 235),
            random.randint(20, 235)
        )
        province_colors[color] = pid

        polys = [geom] if geom.geom_type == "Polygon" else geom.geoms
        for poly in polys:
            coords = geom_to_pixel_coords(poly, bounds, EXPORT_SIZE)
            draw.polygon(coords, fill=color)

    # ---------------------------
    # SEA REGIONS (NO ID!)
    # ---------------------------
    for region in sea_regions:
        color = (
            random.randint(20, 235),
            random.randint(20, 235),
            random.randint(20, 235)
        )

        # DO NOT ADD TO province_colors → sea gets NO ID → PID = -1 in mask
        polys = [region] if region.geom_type == "Polygon" else region.geoms
        for poly in polys:
            coords = geom_to_pixel_coords(poly, bounds, EXPORT_SIZE)
            draw.polygon(coords, fill=color)

    img.save(os.path.join(OUT, "ProvinceMap.png"))
    return province_colors, bounds



# ===============================================================
# EXPORT 2 — ID MAP (ProvinceMask.png)
# ===============================================================

def export_id_map(province_colors):
    """
    Convert ProvinceMap.png → ProvinceMask.png
    """

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

    # MASK
    mask = Image.new("RGB", (w, h))
    px = mask.load()

    for y in range(h):
        for x in range(w):
            pid = id_map[y, x]
            if pid < 0:
                px[x, y] = SEA_COLOR
            else:
                px[x, y] = (pid % 256, pid // 256, 0)

    mask.save(os.path.join(OUT, "ProvinceMask.png"))
    return id_map


# ===============================================================
# SEA OUTLINE DRAWING
# ===============================================================

def draw_voronoi_outline(draw, sea_regions, bounds, size, color):
    for region in sea_regions:
        polys = [region] if region.geom_type == "Polygon" else region.geoms
        for poly in polys:
            coords = geom_to_pixel_coords(poly, bounds, size)
            draw.line(coords, fill=color, width=OUTLINE_WIDTH)


# ===============================================================
# EXPORT 3 — POLITICAL MAP (uniform sea + outline)
# ===============================================================

def export_political_map(id_map, land, sea_regions, bounds):
    h, w = id_map.shape

    # SEA COLOR MUST MATCH THEME MAPS EXACTLY
    img = Image.new("RGB", (w, h), SEA_COLOR)
    draw = ImageDraw.Draw(img)

    # random color per country
    states = sorted(land["country"].unique())
    state_colors = {
        c: (
            random.randint(20, 235),
            random.randint(20, 235),
            random.randint(20, 235)
        )
        for c in states
    }

    province_to_state = land["country"].to_dict()
    px = img.load()

    for y in range(h):
        for x in range(w):
            pid = id_map[y, x]
            if pid < 0:
                continue
            st = province_to_state.get(pid)
            if st:
                px[x, y] = state_colors[st]

    # SAME OUTLINES AS THEME MAPS
    draw_voronoi_outline(draw, sea_regions, bounds, EXPORT_SIZE, OUTLINE_COLOR)

    img.save(os.path.join(OUT, "PoliticalMap.png"))

# ===============================================================
# EXPORT 4 — GENERIC THEME MAP (GDP/POP/IDEOLOGY)
# ===============================================================


def export_theme_map(id_map, bounds, sea_regions, filename, values):
    print("DEBUG THEME MAP: using SEA_COLOR =", SEA_COLOR)

    h, w = id_map.shape

    # === 1) vytvoříme background přesně stejný jako ProvinceMask ===
    img = Image.new("RGB", (w, h))
    px = img.load()

    for y in range(h):
        for x in range(w):
            pid = id_map[y, x]
            if pid < 0:
                px[x, y] = SEA_COLOR
            else:
                px[x, y] = values.get(pid, (120, 120, 120))

    # === 2) outline kreslíme už jen jako čáru – NE polygon ===
    draw = ImageDraw.Draw(img)
    draw_voronoi_outline(draw, sea_regions, bounds, EXPORT_SIZE, OUTLINE_COLOR)

    img.save(os.path.join(OUT, filename))


# ===============================================================
# EXPORT 5 — STATES + STATE FILES
# ===============================================================

def export_states(land):
    states = sorted(land["country"].unique())

    with open(os.path.join(OUT, "States.txt"), "w") as f:
        for st in states:
            R = random.randint(20, 235)
            G = random.randint(20, 235)
            B = random.randint(20, 235)
            f.write(f"{st};{R};{G};{B}\n")


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

# ===============================================================
# EXPORT MODES (GDP / Population / Ideology)
# ===============================================================

def export_mode_folder(mode_name, file_name, description):
    """
    Vytvoří strukturu:
        Modes/<mode_name>/
            <file_name>.png
            manifest.txt
            meta.json
    """
    mode_dir = os.path.join(OUT, "Modes", mode_name)
    os.makedirs(mode_dir, exist_ok=True)

    # 1) Přesun mapy do složky
    src = os.path.join(OUT, f"{file_name}.png")
    dst = os.path.join(mode_dir, f"{file_name}.png")
    if os.path.exists(src):
        os.replace(src, dst)

    # 2) manifest.txt
    manifest_path = os.path.join(mode_dir, "manifest.txt")
    with open(manifest_path, "w") as f:
        f.write(f"mode={mode_name}\n")
        f.write(f"map={file_name}.png\n")

    # 3) meta.json
    meta_path = os.path.join(mode_dir, "meta.json")
    meta = {
        "id": mode_name.lower(),
        "name": mode_name,
        "description": description,
        "map_file": f"{file_name}.png"
    }

    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=4)

    print(f"[EXPORT] Mode folder '{mode_name}' created.")
# ===============================================================
# EXPORT 6 — Provinces.txt (FULL FORMAT FOR GODOT)
# ===============================================================

def export_provinces_txt(province_colors, id_map, land):
    """
    Generates Provinces.txt using the OLD WORKING FORMAT:
    id;R;G;B;type;state;owner;controller;x;y

    - Reads colors from ProvinceMap (province_colors)
    - Reads IDs from id_map
    - land['country'] supplies state/owner/controller
    - Sea provinces are included as type=sea
    """

    out_path = os.path.join(OUT, "Provinces.txt")
    h, w = id_map.shape

    # (R, G, B) → PID mapping already exists in province_colors
    # Reverse: PID → (R,G,B)
    pid_to_color = {pid: col for col, pid in province_colors.items()}

    # Build result rows
    rows = []

    max_pid = int(id_map.max())

    for pid in range(max_pid + 1):

        if pid in pid_to_color:
            # LAND PROVINCE
            R, G, B = pid_to_color[pid]
            st = land.loc[pid]["country"]
            typ = "land"
            owner = st
            controller = st
        else:
            # SHOULD NOT HAPPEN — land provinces always exist in province_colors
            continue

        # Compute centroid pixel coords
        ys, xs = np.where(id_map == pid)
        if len(xs) == 0:
            cx, cy = 0, 0
        else:
            cx = int(xs.mean())
            cy = int(ys.mean())

        rows.append(f"{pid};{R};{G};{B};{typ};{st};{owner};{controller};{cx};{cy}")

    # ----------------------------
    # ADD SEA PROVINCES AS WELL
    # ----------------------------

    used_colors = set(pid_to_color.values())

    # Scan entire image for sea colors
    img = Image.open(os.path.join(OUT, "ProvinceMap.png")).convert("RGB")
    arr = np.array(img)

    sea_seen = {}  # color → sea_id offset

    for y in range(arr.shape[0]):
        for x in range(arr.shape[1]):
            col = tuple(arr[y, x])
            if col not in used_colors:
                # Sea pixel
                if col not in sea_seen:
                    sea_seen[col] = len(seen := sea_seen)  # assign new sea ID

    base_sea_id = max_pid + 1

    for idx, (col, _) in enumerate(sea_seen.items()):
        R, G, B = col
        sea_id = base_sea_id + idx
        rows.append(f"{sea_id};{R};{G};{B};sea;SEA;SEA;SEA;0;0")

    # ----------------------------
    # SAVE FILE
    # ----------------------------
    with open(out_path, "w") as f:
        f.write("id;R;G;B;type;state;owner;controller;x;y\n")
        for r in rows:
            f.write(r + "\n")

    print(f"[EXPORT] Provinces.txt written ({len(rows)} entries).")

# ===============================================================
# MAIN EXPORT ENTRY POINT
# ===============================================================

def run_export(land, sea_regions):

    print("[EXPORT] ProvinceMap…")
    province_colors, bounds = export_province_map(land, sea_regions)

    print("[EXPORT] ProvinceMask…")
    id_map = export_id_map(province_colors)

    print("[EXPORT] PoliticalMap…")
    export_political_map(id_map, land, sea_regions, bounds)

    print("[EXPORT] Provinces.txt…")
    export_provinces_txt(province_colors, id_map, land)


    # ---------------------------------------------------------
    # FIX: zajistí, že values obsahuje hodnotu pro všechny PID,
    # včetně moře, aby se nikdy nepoužil defaultní šedý background.
    # ---------------------------------------------------------
    max_pid = int(id_map.max())
    print(f"[DEBUG] MAX PID DETECTED = {max_pid}")

    # ===============================
    # GDP MAP
    # ===============================
    print("[EXPORT] GDP Map…")
    gdp_values = {
        pid: (random.randint(120, 255), 50, 50)   # červené odstíny
        for pid in range(max_pid + 1)
    }
    export_theme_map(id_map, bounds, sea_regions, "GDPMap.png", gdp_values)

    # ===============================
    # POPULATION MAP
    # ===============================
    print("[EXPORT] Population Map…")
    pop_values = {
        pid: (50, random.randint(120, 255), 50)   # zelené odstíny
        for pid in range(max_pid + 1)
    }
    export_theme_map(id_map, bounds, sea_regions, "PopulationMap.png", pop_values)

    # ===============================
    # IDEOLOGY MAP
    # ===============================
    print("[EXPORT] Ideology Map…")
    ideo_values = {
        pid: (50, 50, random.randint(120, 255))   # modré odstíny
        for pid in range(max_pid + 1)
    }
    export_theme_map(id_map, bounds, sea_regions, "IdeologyMap.png", ideo_values)
    
    # ===============================
    # STATES + STATE FILES
    # ===============================
    export_states(land)
    export_state_files(land)
    # Move maps into mode folders
    export_mode_folder("GDP", "GDPMap", "Gross Domestic Product heatmap")
    export_mode_folder("Population", "PopulationMap", "Population density map")
    export_mode_folder("Ideology", "IdeologyMap", "Ideological spectrum map")

    print("✔ EXPORT COMPLETE")

