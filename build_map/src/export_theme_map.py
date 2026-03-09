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


def export_population_map(
    id_map,
    sea_regions,
    bounds,
    population=None,
    land_areas=None,
    population_source=None,
    province_country=None,
    max_pid=None,
):
    """
    population: dict pid -> population number
    land_areas: dict pid -> area in km^2
    population_source: dict pid -> source label (matched_*/imputed_*)
    province_country: dict pid -> country name

    Rendering rule:
    - use global density scale for all provinces (stable cross-country meaning)
    - add mild within-country variation for imputed_* provinces so constant-density fills are not flat
    """
    max_pid = max_pid if max_pid is not None else int(id_map.max())

    pop_values = None
    metric = None
    metric_t = None

    if population:
        metric = {}
        for pid in range(max_pid + 1):
            pop = population.get(pid, 0) or 0
            if pop <= 0:
                metric[pid] = 0
                continue

            if land_areas:
                metric[pid] = pop / land_areas.get(pid, 1)
            else:
                metric[pid] = pop

    if metric:
        vals = [v for v in metric.values() if v > 0]
        if vals:
            log_min = min(math.log10(v) for v in vals)
            log_max = max(math.log10(v) for v in vals)
            span = log_max - log_min or 1.0

            metric_t = {}
            for pid in range(max_pid + 1):
                v = metric.get(pid, 0)
                if v <= 0:
                    metric_t[pid] = 0.0
                    continue
                metric_t[pid] = (math.log10(v) - log_min) / span

            if population_source and province_country:
                country_pop_values = {}
                for pid in range(max_pid + 1):
                    pop = population.get(pid, 0) or 0
                    if pop <= 0:
                        continue
                    country = province_country.get(pid, "")
                    if not country:
                        continue
                    country_pop_values.setdefault(country, []).append(math.log10(pop))

                country_log_bounds = {}
                for country, logs in country_pop_values.items():
                    country_log_bounds[country] = (min(logs), max(logs))

                for pid in range(max_pid + 1):
                    source = population_source.get(pid, "")
                    if not source.startswith("imputed_"):
                        continue

                    pop = population.get(pid, 0) or 0
                    if pop <= 0:
                        continue

                    country = province_country.get(pid, "")
                    country_bounds = country_log_bounds.get(country)
                    if not country_bounds:
                        continue

                    cmin, cmax = country_bounds
                    cspan = cmax - cmin
                    local_t = 0.5 if cspan <= 1e-12 else (math.log10(pop) - cmin) / cspan
                    base_t = metric_t.get(pid, 0.0)
                    metric_t[pid] = max(0.0, min(1.0, 0.7 * base_t + 0.3 * local_t))

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
                t = metric_t.get(pid, 0.0) if metric_t is not None else (math.log10(v) - log_min) / span
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
    export_mode_folder("Population", "PopulationMap", "Population map")


def export_ideology_map(id_map, sea_regions, bounds, max_pid=None):
    max_pid = max_pid if max_pid is not None else int(id_map.max())
    ideo_values = {
        pid: (50, 50, random.randint(120, 255))
        for pid in range(max_pid + 1)
    }
    export_theme_map(id_map, bounds, sea_regions, "IdeologyMap.png", ideo_values)
    export_mode_folder("Ideology", "IdeologyMap", "Ideological spectrum map")
