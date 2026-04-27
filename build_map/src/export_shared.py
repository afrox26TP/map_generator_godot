import os

# HELPED BY AI
EXPORT_SIZE = 4096
SEA_COLOR = (20, 80, 200)
OUTLINE_COLOR = (0, 32, 96)
OUTLINE_WIDTH = 1

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "opengs_export")

os.makedirs(OUT, exist_ok=True)
os.makedirs(os.path.join(OUT, "States"), exist_ok=True)


def geom_to_pixel_coords(geom, bounds, size):
    return ring_to_pixel_coords(geom.exterior, bounds, size)


def ring_to_pixel_coords(ring, bounds, size):
    minx, miny, maxx, maxy = bounds
    w = size
    h = size

    dx = maxx - minx
    dy = maxy - miny
    if dx == 0 or dy == 0:
        return []

    coords = []
    for x, y in ring.coords:
        # Round to nearest pixel center to reduce directional bias on borders.
        px_f = (x - minx) / dx * (w - 1)
        py_f = (1 - (y - miny) / dy) * (h - 1)

        px = int(round(px_f))
        py = int(round(py_f))

        if px < 0:
            px = 0
        elif px >= w:
            px = w - 1

        if py < 0:
            py = 0
        elif py >= h:
            py = h - 1

        point = (px, py)
        if not coords or coords[-1] != point:
            coords.append(point)

    # Keep ring closed for robust polygon filling.
    if len(coords) >= 2 and coords[0] != coords[-1]:
        coords.append(coords[0])

    return coords


def draw_voronoi_outline(draw, sea_regions, bounds, size, color):
    for region in sea_regions:
        polys = [region] if region.geom_type == "Polygon" else region.geoms
        for poly in polys:
            coords = geom_to_pixel_coords(poly, bounds, size)
            draw.line(coords, fill=color, width=OUTLINE_WIDTH)
