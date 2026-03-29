import json
import os
import random
import math
import shutil
import time
import re
import unicodedata
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
    map_filename = f"{file_name}.png"
    if os.path.exists(src):
        try:
            os.replace(src, dst)
        except PermissionError:
            # Destination may be locked by an external viewer; write a fallback file.
            fallback_name = f"{file_name}_{int(time.time())}.png"
            fallback_dst = os.path.join(mode_dir, fallback_name)
            shutil.copy2(src, fallback_dst)
            map_filename = fallback_name
            print(
                f"[WARN] {dst} is locked. Wrote fallback map '{fallback_name}' instead."
            )

    manifest_path = os.path.join(mode_dir, "manifest.txt")
    with open(manifest_path, "w") as f:
        f.write(f"mode={mode_name}\n")
        f.write(f"map={map_filename}\n")

    meta_path = os.path.join(mode_dir, "meta.json")
    meta = {
        "id": mode_name.lower(),
        "name": mode_name,
        "description": description,
        "map_file": map_filename,
    }

    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=4)

    print(f"[EXPORT] Mode folder '{mode_name}' created.")


def export_gdp_map(id_map, sea_regions, bounds, gdp=None, max_pid=None):
    max_pid = max_pid if max_pid is not None else int(id_map.max())

    gdp_colors = None
    if gdp:
        metric = {
            pid: max(float(gdp.get(pid, 0.0) or 0.0), 0.0)
            for pid in range(max_pid + 1)
        }
        vals = [v for v in metric.values() if v > 0]

        if vals:
            log_min = min(math.log10(v) for v in vals)
            log_max = max(math.log10(v) for v in vals)
            span = log_max - log_min or 1.0

            def lerp(a, b, t):
                return int(a + (b - a) * t)

            low = (245, 233, 184)   # light sand
            high = (155, 22, 22)    # deep red

            gdp_colors = {}
            for pid in range(max_pid + 1):
                v = metric.get(pid, 0.0)
                if v <= 0:
                    gdp_colors[pid] = (120, 120, 120)
                    continue

                t = (math.log10(v) - log_min) / span
                gdp_colors[pid] = (
                    lerp(low[0], high[0], t),
                    lerp(low[1], high[1], t),
                    lerp(low[2], high[2], t),
                )

    if gdp_colors is None:
        gdp_colors = {
            pid: (random.randint(120, 255), 50, 50)
            for pid in range(max_pid + 1)
        }

    export_theme_map(id_map, bounds, sea_regions, "GDPMap.png", gdp_colors)
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
                    if source.startswith("matched_"):
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

                    # Keep region-guided countries closer to global scale to avoid over-contrast.
                    if source.startswith("region_scaled_official"):
                        base_weight = 0.9
                    elif source.startswith("imputed_"):
                        base_weight = 0.8
                    else:
                        base_weight = 0.75

                    metric_t[pid] = max(
                        0.0,
                        min(1.0, base_weight * base_t + (1.0 - base_weight) * local_t),
                    )

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


def export_recruitable_population_map(
    id_map,
    sea_regions,
    bounds,
    recruitable_population=None,
    max_pid=None,
):
    max_pid = max_pid if max_pid is not None else int(id_map.max())

    recruit_values = None
    if recruitable_population:
        metric = {
            pid: max(float(recruitable_population.get(pid, 0) or 0.0), 0.0)
            for pid in range(max_pid + 1)
        }
        vals = [v for v in metric.values() if v > 0]

        if vals:
            log_min = min(math.log10(v) for v in vals)
            log_max = max(math.log10(v) for v in vals)
            span = log_max - log_min or 1.0

            def lerp(a, b, t):
                return int(a + (b - a) * t)

            low = (252, 234, 206)   # light amber
            high = (168, 45, 0)     # burnt orange

            recruit_values = {}
            for pid in range(max_pid + 1):
                v = metric.get(pid, 0.0)
                if v <= 0:
                    recruit_values[pid] = (120, 120, 120)
                    continue

                t = (math.log10(v) - log_min) / span
                recruit_values[pid] = (
                    lerp(low[0], high[0], t),
                    lerp(low[1], high[1], t),
                    lerp(low[2], high[2], t),
                )

    if recruit_values is None:
        recruit_values = {
            pid: (random.randint(170, 255), random.randint(90, 170), 30)
            for pid in range(max_pid + 1)
        }

    export_theme_map(
        id_map,
        bounds,
        sea_regions,
        "RecruitablePopulationMap.png",
        recruit_values,
    )
    export_mode_folder(
        "RecruitablePopulation",
        "RecruitablePopulationMap",
        "Recruitable population map",
    )


def export_happiness_map(
    id_map,
    sea_regions,
    bounds,
    happiness=None,
    max_pid=None,
):
    max_pid = max_pid if max_pid is not None else int(id_map.max())

    happiness_values = None
    if happiness:
        metric = {
            pid: max(0.0, min(100.0, float(happiness.get(pid, 0) or 0.0)))
            for pid in range(max_pid + 1)
        }

        def lerp(a, b, t):
            return int(a + (b - a) * t)

        low = (184, 36, 44)    # unhappy red
        mid = (247, 197, 72)   # neutral amber
        high = (36, 148, 82)   # happy green

        happiness_values = {}
        for pid in range(max_pid + 1):
            score = metric.get(pid, 0.0)
            t = score / 100.0

            if t <= 0.5:
                t2 = t / 0.5
                happiness_values[pid] = (
                    lerp(low[0], mid[0], t2),
                    lerp(low[1], mid[1], t2),
                    lerp(low[2], mid[2], t2),
                )
            else:
                t2 = (t - 0.5) / 0.5
                happiness_values[pid] = (
                    lerp(mid[0], high[0], t2),
                    lerp(mid[1], high[1], t2),
                    lerp(mid[2], high[2], t2),
                )

    if happiness_values is None:
        happiness_values = {
            pid: (
                random.randint(120, 240),
                random.randint(120, 220),
                random.randint(60, 180),
            )
            for pid in range(max_pid + 1)
        }

    export_theme_map(id_map, bounds, sea_regions, "HappinessMap.png", happiness_values)
    export_mode_folder("Happiness", "HappinessMap", "Population happiness map")


TERRAIN_COLORS = {
    "city": (130, 130, 130),
    "plains": (199, 216, 133),
    "forest": (57, 122, 66),
    "hills": (157, 171, 105),
    "mountains": (116, 102, 90),
}


def export_terrain_map(
    id_map,
    sea_regions,
    bounds,
    terrain_by_pid=None,
    max_pid=None,
):
    max_pid = max_pid if max_pid is not None else int(id_map.max())

    terrain_values = {}
    for pid in range(max_pid + 1):
        terrain = "plains"
        if terrain_by_pid:
            terrain = str(terrain_by_pid.get(pid, "plains") or "plains").strip().lower()
        terrain_values[pid] = TERRAIN_COLORS.get(terrain, TERRAIN_COLORS["plains"])

    export_theme_map(id_map, bounds, sea_regions, "TerrainMap.png", terrain_values)
    export_mode_folder("Terrain", "TerrainMap", "Province terrain type map")


RESOURCE_COLORS = {
    "none": (120, 120, 120),
    "grain": (214, 192, 108),
    "timber": (63, 132, 74),
    "iron": (121, 126, 139),
    "coal": (72, 72, 78),
    "oil": (32, 40, 52),
    "gas": (106, 167, 201),
    "gold": (214, 171, 52),
    "uranium": (120, 196, 92),
}


def export_resources_map(
    id_map,
    sea_regions,
    bounds,
    resources_by_pid=None,
    max_pid=None,
):
    max_pid = max_pid if max_pid is not None else int(id_map.max())

    resource_values = {}
    for pid in range(max_pid + 1):
        record = (resources_by_pid or {}).get(pid, {})
        resource_type = str(record.get("resource_type") or "none").strip().lower()
        resource_amount = int(record.get("resource_amount") or 0)
        base_color = RESOURCE_COLORS.get(resource_type, RESOURCE_COLORS["none"])

        # Encode deposit strength by gentle brightness shift.
        factor = 0.78 + (max(0, min(100, resource_amount)) / 100.0) * 0.32
        resource_values[pid] = tuple(
            max(0, min(255, int(channel * factor)))
            for channel in base_color
        )

    export_theme_map(id_map, bounds, sea_regions, "ResourcesMap.png", resource_values)
    export_mode_folder("Resources", "ResourcesMap", "Province resource deposits map")


IDEOLOGY_COLORS = {
    "demokracie": (64, 122, 205),
    "kralovstvi": (212, 175, 55),
    "autokracie": (186, 62, 62),
    "unknown": (120, 120, 120),
}


def _normalize_ideology_label(value):
    if value is None:
        return "unknown"

    text = str(value).strip().lower()
    if not text:
        return "unknown"

    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9]+", " ", text).strip()

    if not text:
        return "unknown"
    if text in {"demokracie", "democracy", "democratic"}:
        return "demokracie"
    if text in {"kralovstvi", "kralostvi", "monarchy", "kingdom", "constitutional monarchy"}:
        return "kralovstvi"
    if text in {"autokracie", "autocracy", "autocratic", "dictatorship"}:
        return "autokracie"

    if "democr" in text or "demokra" in text:
        return "demokracie"
    if "kralov" in text or "kralost" in text or "monarch" in text or "kingdom" in text:
        return "kralovstvi"
    if "autocr" in text or "diktat" in text or "dictat" in text:
        return "autokracie"

    return "unknown"


def export_ideology_map(id_map, sea_regions, bounds, ideology_by_pid=None, max_pid=None):
    max_pid = max_pid if max_pid is not None else int(id_map.max())

    if ideology_by_pid:
        ideo_values = {}
        for pid in range(max_pid + 1):
            ideology_key = _normalize_ideology_label(ideology_by_pid.get(pid))
            ideo_values[pid] = IDEOLOGY_COLORS.get(
                ideology_key,
                IDEOLOGY_COLORS["unknown"],
            )
    else:
        ideo_values = {
            pid: (50, 50, random.randint(120, 255))
            for pid in range(max_pid + 1)
        }

    export_theme_map(id_map, bounds, sea_regions, "IdeologyMap.png", ideo_values)
    export_mode_folder("Ideology", "IdeologyMap", "Government type map")


