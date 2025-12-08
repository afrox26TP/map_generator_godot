import json
import os
import random
import math
from PIL import Image, ImageDraw

from export_shared import EXPORT_SIZE, SEA_COLOR, OUTLINE_COLOR, OUT, draw_voronoi_outline


def export_theme_map(id_map, bounds, sea_regions, filename, values):
    h, w = id_map.shape

    img = Image.new("RGB", (w, h))
    px = img.load()

    for y in range(h):
        for x in range(w):
            pid = id_map[y, x]
            if pid < 0:
                px[x, y] = SEA_COLOR
            else:
                px[x, y] = values.get(pid, (120, 120, 120))

    draw = ImageDraw.Draw(img)
    draw_voronoi_outline(draw, sea_regions, bounds, EXPORT_SIZE, OUTLINE_COLOR)

    img.save(os.path.join(OUT, filename))


def export_mode_folder(mode_name, file_name, description):
    mode_dir = os.path.join(OUT, "Modes", mode_name)
    os.makedirs(mode_dir, exist_ok=True)

    src = os.path.join(OUT, f"{file_name}.png")
    dst = os.path.join(mode_dir, f"{file_name}.png")
    if os.path.exists(src):
        os.replace(src, dst)

    manifest_path = os.path.join(mode_dir, "manifest.txt")
    with open(manifest_path, "w") as f:
        f.write(f"mode={mode_name}\n")
        f.write(f"map={file_name}.png\n")

    meta_path = os.path.join(mode_dir, "meta.json")
    meta = {
        "id": mode_name.lower(),
        "name": mode_name,
        "description": description,
        "map_file": f"{file_name}.png",
    }

    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=4)

    print(f"[EXPORT] Mode folder '{mode_name}' created.")


def export_gdp_map(id_map, sea_regions, bounds, max_pid=None):
    max_pid = max_pid if max_pid is not None else int(id_map.max())
    gdp_values = {
        pid: (random.randint(120, 255), 50, 50)
        for pid in range(max_pid + 1)
    }
    export_theme_map(id_map, bounds, sea_regions, "GDPMap.png", gdp_values)
    export_mode_folder("GDP", "GDPMap", "Gross Domestic Product heatmap")


def export_population_map(id_map, sea_regions, bounds, population=None, land_areas=None, max_pid=None):
    """
    population: dict pid -> population number
    land_areas: dict pid -> area in km^2 (for density). If provided, density is used; otherwise raw pop.
    """
    max_pid = max_pid if max_pid is not None else int(id_map.max())

    pop_values = None
    metric = None

    if population:
        if land_areas:
            metric = {
                pid: (population.get(pid) or 0) / land_areas.get(pid, 1)
                for pid in range(max_pid + 1)
            }
        else:
            metric = {pid: population.get(pid, 0) for pid in range(max_pid + 1)}

    if metric:
        vals = [v for v in metric.values() if v > 0]
        if vals:
            log_min = min(math.log10(v) for v in vals)
            log_max = max(math.log10(v) for v in vals)
            span = log_max - log_min or 1.0

            def lerp(a, b, t):
                return int(a + (b - a) * t)

            low = (190, 230, 150)   # light green
            high = (0, 120, 0)      # dark green

            pop_values = {}
            for pid in range(max_pid + 1):
                v = metric.get(pid, 0)
                if v <= 0:
                    pop_values[pid] = (120, 120, 120)
                    continue
                t = (math.log10(v) - log_min) / span
                pop_values[pid] = (
                    lerp(low[0], high[0], t),
                    lerp(low[1], high[1], t),
                    lerp(low[2], high[2], t),
                )

    if pop_values is None:
        pop_values = {
            pid: (50, random.randint(120, 255), 50)
            for pid in range(max_pid + 1)
        }

    export_theme_map(id_map, bounds, sea_regions, "PopulationMap.png", pop_values)
    export_mode_folder("Population", "PopulationMap", "Population density map")


def export_ideology_map(id_map, sea_regions, bounds, max_pid=None):
    max_pid = max_pid if max_pid is not None else int(id_map.max())
    ideo_values = {
        pid: (50, 50, random.randint(120, 255))
        for pid in range(max_pid + 1)
    }
    export_theme_map(id_map, bounds, sea_regions, "IdeologyMap.png", ideo_values)
    export_mode_folder("Ideology", "IdeologyMap", "Ideological spectrum map")
