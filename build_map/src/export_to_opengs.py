import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point, Polygon, MultiPolygon
from PIL import Image, ImageDraw
import os
import random
import json

# ===============================================================
# CONFIG
# ===============================================================

EXPORT_SIZE = 4096   # velikost map pro Godot

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "opengs_export")

os.makedirs(OUT, exist_ok=True)
os.makedirs(os.path.join(OUT, "States"), exist_ok=True)


# ===============================================================
# UNIQUE COLOR GENERATOR
# ===============================================================

def generate_colors(n):
    used = set()
    colors = []

    while len(colors) < n:
        R = random.randint(1, 255)
        G = random.randint(1, 255)
        B = random.randint(1, 255)

        if (R, G, B) not in used:
            used.add((R, G, B))
            colors.append((R, G, B))

    return colors


# ===============================================================
# RASTERIZATION — FIXED WITH BUFFER TO AVOID GAPS
# ===============================================================

def rasterize_provinces(gdf, colors, export_size):
    minx, miny, maxx, maxy = gdf.total_bounds
    width = export_size
    height = export_size

    img = Image.new("RGB", (width, height), (0, 0, 0))
    draw = ImageDraw.Draw(img)

    for (idx, row), color in zip(gdf.iterrows(), colors):
        geom = row.geometry.buffer(30)  # FIX pixel gaps

        if geom.is_empty:
            continue

        polys = [geom] if geom.geom_type == "Polygon" else geom.geoms

        for poly in polys:
            coords = []
            for x, y in poly.exterior.coords:
                px = int((x - minx) / (maxx - minx) * width)
                py = int((1 - (y - miny) / (maxy - miny)) * height)
                coords.append((px, py))

            draw.polygon(coords, fill=color)

    return img


# ===============================================================
# EXPORT PROVINCES + Provinces.txt
# ===============================================================

def export_provinces(land, sea_regions):
    land["type"] = "land"

    sea_df = gpd.GeoDataFrame({
        "geometry": sea_regions,
        "country": ["SEA"] * len(sea_regions),
        "type": ["sea"] * len(sea_regions)
    }, crs=land.crs)

    full = pd.concat([land, sea_df], ignore_index=True)

    colors = generate_colors(len(full))

    print(f"[EXPORT] Total provinces: {len(full)}")

    img = rasterize_provinces(full, colors, EXPORT_SIZE)
    img.save(os.path.join(OUT, "ProvinceMap.png"))

    # write txt
    lines = ["id;R;G;B;type;state;owner;controller;x;y"]

    for i, ((idx, row), (R, G, B)) in enumerate(zip(full.iterrows(), colors)):
        lines.append(f"{i};{R};{G};{B};{row['type']};{row['country']};"
                     f"{row['country']};{row['country']};0;0")

    with open(os.path.join(OUT, "Provinces.txt"), "w") as f:
        f.write("\n".join(lines))

    return full, colors


# ===============================================================
# EXPORT ProvinceMask.png — UNIQUE COLOR PER PROVINCE
# ===============================================================

def export_province_mask(full_df, export_size, colors):

    print("[EXPORT] Generating ProvinceMask.png")

    minx, miny, maxx, maxy = full_df.total_bounds
    width = export_size
    height = export_size

    img = Image.new("RGB", (width, height), (0, 0, 0))
    draw = ImageDraw.Draw(img)

    for (idx, row), (R, G, B) in zip(full_df.iterrows(), colors):

        geom = row.geometry
        if geom.is_empty:
            continue

        polys = [geom] if geom.geom_type == "Polygon" else geom.geoms

        for poly in polys:
            coords = []
            for x, y in poly.exterior.coords:
                px = int((x - minx) / (maxx - minx) * width)
                py = int((1 - (y - miny) / (maxy - miny)) * height)
                coords.append((px, py))

            draw.polygon(coords, fill=(R, G, B))

    out_path = os.path.join(OUT, "ProvinceMask.png")
    img.save(out_path)

    print(f"[OK] ProvinceMask.png saved → {out_path}")


# ===============================================================
# EXPORT States.txt
# ===============================================================

def export_states(full_df):
    states = sorted(full_df["country"].unique())
    colors = generate_colors(len(states))

    lines = []
    for state, (R, G, B) in zip(states, colors):
        lines.append(f"{state};{R};{G};{B}")

    with open(os.path.join(OUT, "States.txt"), "w") as f:
        f.write("\n".join(lines))


# ===============================================================
# EXPORT FILES FOR OPENGS FORMAT
# ===============================================================

def export_opengs_state_files(full_df):
    states = sorted(full_df["country"].unique())
    state_id = 1
    folder = os.path.join(OUT, "States")

    for tag in states:
        if tag == "SEA":
            continue

        provs = full_df.index[full_df["country"] == tag].tolist()

        with open(os.path.join(folder, f"{state_id}_{tag}.txt"), "w") as f:
            f.write("state={\n")
            f.write(f"    id={state_id}\n")
            f.write(f"    name=\"STATE_{tag}\"\n")
            f.write("    provinces={\n")

            for p in provs:
                f.write(f"        {p}\n")

            f.write("    }\n")
            f.write("}\n")
            f.write("manpower=0\n")
            f.write("buildings_max_level_factor=1.000\n")

        state_id += 1

    print(f"[OK] OpenGS state files saved → {folder}")


# ===============================================================
# EXPORT POLITICAL MAP (State-colored)
# ===============================================================

def export_political_map(full_df, export_size):
    minx, miny, maxx, maxy = full_df.total_bounds
    width = export_size
    height = export_size

    states = sorted(full_df["country"].unique())
    colors = generate_colors(len(states))

    color_map = {state: col for state, col in zip(states, colors)}
    color_map["SEA"] = (0, 0, 0)

    img = Image.new("RGB", (width, height), (0, 0, 0))
    draw = ImageDraw.Draw(img)

    for idx, row in full_df.iterrows():
        geom = row.geometry
        if geom.is_empty:
            continue

        col = color_map[row["country"]]
        polys = [geom] if geom.geom_type == "Polygon" else geom.geoms

        for poly in polys:
            coords = []
            for x, y in poly.exterior.coords:
                px = int((x - minx) / (maxx - minx) * width)
                py = int((1 - (y - miny) / (maxy - miny)) * height)
                coords.append((px, py))

            draw.polygon(coords, fill=col)

    out = os.path.join(OUT, "PoliticalMap.png")
    img.save(out)
    print(f"[OK] PoliticalMap.png saved → {out}")


# ===============================================================
# MAIN EXPORT FUNCTION
# ===============================================================

def run_export(land, final_regions):

    full_df, colors = export_provinces(land, final_regions)

    export_province_mask(full_df, EXPORT_SIZE, colors)
    export_states(full_df)
    export_opengs_state_files(full_df)
    export_political_map(full_df, EXPORT_SIZE)

    print("\n==============================")
    print("✔ EXPORT COMPLETE")
    print("✔ ProvinceMap.png")
    print("✔ ProvinceMask.png")
    print("✔ PoliticalMap.png")
    print("✔ Provinces.txt")
    print("✔ States.txt")
    print("==============================\n")
