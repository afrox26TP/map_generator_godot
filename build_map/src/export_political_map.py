import os
import random
from PIL import Image, ImageDraw

from export_shared import EXPORT_SIZE, SEA_COLOR, OUTLINE_COLOR, OUT, draw_voronoi_outline


def export_political_map(id_map, land, sea_regions, bounds):
    h, w = id_map.shape

    img = Image.new("RGB", (w, h), SEA_COLOR)
    draw = ImageDraw.Draw(img)

    states = sorted(land["country"].unique())
    state_colors = {
        c: (
            random.randint(20, 235),
            random.randint(20, 235),
            random.randint(20, 235),
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

    draw_voronoi_outline(draw, sea_regions, bounds, EXPORT_SIZE, OUTLINE_COLOR)

    img.save(os.path.join(OUT, "PoliticalMap.png"))
