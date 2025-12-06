# =====================================================================
# IMPORTS + CONFIG
# =====================================================================

import geopandas as gpd
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

from shapely.geometry import box, Point, MultiPoint, Polygon, MultiPolygon
from shapely.ops import unary_union, voronoi_diagram
import os, random

DEBUG = True
def debug(msg):
    if DEBUG:
        print(f"[DEBUG] {msg}")

BASE = os.path.dirname(os.path.abspath(__file__))


# =====================================================================
# PART 1 — LOAD ADMIN1 + FIX EUROPE + CUT RUSSIA + ADD CAUCASUS + ISLANDS
# =====================================================================

debug("PART 1 START — loading & filtering admin1")

admin = gpd.read_file(os.path.join(BASE, "ne_10m_admin_1_states_provinces.shp"))
admin = admin.to_crs(3035)
admin["geometry"] = admin.geometry.buffer(0)

# -----------------------------
# LIST OF COUNTRIES TO KEEP
# -----------------------------
EUROPE_COUNTRIES = [
    # Core EU + EEA
    "ISL","IRL","GBR","PRT","ESP","FRA","AND","BEL","NLD","LUX",
    "DEU","CHE","AUT","LIE","ITA","SMR","MLT",
    "DNK","NOR","SWE","FIN",
    "EST","LVA","LTU",
    "POL","CZE","SVK","HUN",
    "SVN","HRV","BIH","SRB","MNE","MKD","ALB","KOS",
    "GRC","CYP",  # Cyprus added

    # East
    "BGR","ROU","MDA","UKR","BLR",

    # Russia (will cut)
    "RUS",

    # Caucasus (add back)
    "ARM","GEO","AZE",
    
    # Turkey (only part will be visible after cropping)
    "TUR"
]

admin["country"] = admin["adm0_a3"]
admin = admin[admin["country"].isin(EUROPE_COUNTRIES)].reset_index(drop=True)

debug(f"Regions loaded after country filter: {len(admin)}")

# -----------------------------
# FIX: Cut RUSSIA to EUROPE part
# -----------------------------
def cut_russia(geom):
    europe_lonlat = box(20, 35, 60, 75)  # 20E–60E, 35N–75N
    europe_3035 = gpd.GeoSeries([europe_lonlat], crs=4326).to_crs(3035).iloc[0]
    return geom.intersection(europe_3035)

rus = admin[admin["country"] == "RUS"].copy()
admin = admin[admin["country"] != "RUS"]

rus["geometry"] = rus.geometry.apply(cut_russia)
rus = rus[~rus.geometry.is_empty]

admin = pd.concat([admin, rus], ignore_index=True)

# -----------------------------
# REMOVE GEOMETRIES OUTSIDE EUROPE AREA
# -----------------------------
# This bounding box keeps Med islands, Cyprus, Iceland, Caucasus
minx, miny, maxx, maxy = 900000, 1000000, 7000000, 6500000
admin = admin.cx[minx:maxx, miny:maxy]

debug(f"Final part-1 regions: {len(admin)}")
debug("PART 1 DONE")


# =====================================================================
# PART 2 — CLEAN GEOMETRY
# =====================================================================

debug("PART 2 START — cleaning geometry")

def remove_holes(g):
    if g.geom_type == "Polygon":
        return Polygon(g.exterior)
    elif g.geom_type == "MultiPolygon":
        return MultiPolygon([Polygon(p.exterior) for p in g.geoms])
    return g

admin["geometry"] = admin.geometry.apply(remove_holes)
admin["geometry"] = admin.geometry.buffer(0)

land = admin.copy()
land_union = unary_union(land.geometry)

debug(f"PART 2 DONE — valid regions: {len(land)}")
debug("Before merge small: " + str(len(land)))

# =====================================================================
# PART 2.5 — MERGING OF SMALL REGIONS (ABSOLUTE THRESHOLD ONLY)
# =====================================================================

debug("PART 2.5 START — merging small provinces...")

from shapely.geometry import Polygon, MultiPolygon

# --------------------------
# CONSTANT AREA MERGE THRESHOLD
# --------------------------
MIN_AREA_ABS = 1_000_000_000   # cokoliv menší než 10M m² se sloučí


def merge_small_absolute(gdf):
    gdf = gdf.copy()
    gdf["area"] = gdf.geometry.area

    merged = []

    for country, group in gdf.groupby("country"):
        group = group.copy()

        while True:
            small = group[group["area"] < MIN_AREA_ABS]

            if small.empty:
                break

            idx = small.index[0]
            target = group.loc[idx]

            # candidates ONLY in the same country
            candidates = group.drop(idx)
            if candidates.empty:
                group = group.drop(idx)
                continue

            # merge with nearest polygon
            nearest_idx = candidates.distance(target.geometry).sort_values().index[0]
            merged_geom = target.geometry.union(group.loc[nearest_idx].geometry)

            group.loc[nearest_idx, "geometry"] = merged_geom
            group = group.drop(idx)
            group["area"] = group.geometry.area

        merged.append(group)

    merged = pd.concat(merged, ignore_index=True)
    return merged.drop(columns="area")


# Apply merge
land = merge_small_absolute(land)

debug(f"PART 2.5 DONE ")

# =====================================================================
# PART 3 — SEA REGIONS (unchanged)
# =====================================================================
debug("After merge small: " + str(len(land)))

debug("PART 3 START — generating sea regions")

minx, miny, maxx, maxy = land.total_bounds

outer = box(minx - 100000, miny - 100000, maxx + 100000, maxy + 100000)
sea = outer.difference(land_union)

# sample sea points
points = []
for _ in range(15000):
    x = np.random.uniform(minx, maxx)
    y = np.random.uniform(miny, maxy)
    p = Point(x, y)
    if sea.contains(p):
        points.append([x, y])

points = np.array(points)
debug(f"Sea points: {len(points)}")

# clustering
from sklearn.cluster import KMeans
N_REGIONS = 60

kmeans = KMeans(n_clusters=N_REGIONS, n_init="auto")
centers = kmeans.fit(points).cluster_centers_

vor = voronoi_diagram(MultiPoint([Point(c[0], c[1]) for c in centers]))

final_regions = []
for poly in vor.geoms:
    clipped = poly.intersection(sea)
    if clipped.is_empty:
        continue

    # smooth edges
    try:
        clipped = clipped.buffer(15000).buffer(-15000)
    except:
        pass

    if not clipped.is_empty:
        final_regions.append(clipped)

debug(f"Sea regions generated: {len(final_regions)}")
debug("PART 3 DONE")


# =====================================================================
# PART 4 — PREVIEW
# =====================================================================

debug("PART 4 START — generating preview image")

fig, ax = plt.subplots(figsize=(18, 12))

# sea
for region in final_regions:
    color = (random.random(), random.random(), random.random(), 0.7)
    if region.geom_type == "MultiPolygon":
        for p in region.geoms:
            xs, ys = p.exterior.xy
            ax.fill(xs, ys, color=color)
    else:
        xs, ys = region.exterior.xy
        ax.fill(xs, ys, color=color)

# land borders
land.boundary.plot(ax=ax, color="white", linewidth=0.6)

ax.set_axis_off()
fig.savefig(os.path.join(BASE, "preview_map.png"), dpi=350)
plt.close(fig)

debug("PART 4 DONE")


# =====================================================================
# PART 5 — EXPORT TO OPENGS
# =====================================================================

debug("Starting export...")

from export_to_opengs import run_export
run_export(land, final_regions)

debug("Export complete.")
