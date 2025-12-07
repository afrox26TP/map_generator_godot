import os

EXPORT_SIZE = 4096
SEA_COLOR = (20, 80, 200)
OUTLINE_COLOR = (0, 32, 96)
OUTLINE_WIDTH = 1

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "opengs_export")

os.makedirs(OUT, exist_ok=True)
os.makedirs(os.path.join(OUT, "States"), exist_ok=True)


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


def draw_voronoi_outline(draw, sea_regions, bounds, size, color):
    for region in sea_regions:
        polys = [region] if region.geom_type == "Polygon" else region.geoms
        for poly in polys:
            coords = geom_to_pixel_coords(poly, bounds, size)
            draw.line(coords, fill=color, width=OUTLINE_WIDTH)
