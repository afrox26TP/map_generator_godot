import json
import os
import random
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


def export_population_map(id_map, sea_regions, bounds, max_pid=None):
    max_pid = max_pid if max_pid is not None else int(id_map.max())
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
