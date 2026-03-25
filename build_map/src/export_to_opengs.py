import json
import os
import random
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage as ndi

from export_shared import EXPORT_SIZE, SEA_COLOR, OUT, geom_to_pixel_coords, ring_to_pixel_coords
from export_political_map import export_political_map
from export_theme_map import (
    export_gdp_map,
    export_population_map,
    export_recruitable_population_map,
    export_ideology_map,
)
from import_population import generate_population_dataset
from import_gdp import generate_gdp_dataset
from import_ideology import canonical_ideology, generate_ideology_dataset
from import_relationships import generate_relationship_dataset


RECRUITABLE_SHARE_BY_IDEOLOGY = {
    "demokracie": 0.05,
    "kralovstvi": 0.10,
    "autokracie": 0.15,
}
DEFAULT_RECRUITABLE_SHARE = RECRUITABLE_SHARE_BY_IDEOLOGY["demokracie"]
CAPITAL_RECRUITABLE_MULTIPLIER = 3.0
PROVINCE_RENDER_SUPERSAMPLE = 2
THIN_BRIDGE_MAX_WIDTH_PX = 4


def _write_custom_island_flag():
    """Write a custom furry-themed flag for the AEO custom island."""
    flags_dir = os.path.join(OUT, "Flags")
    os.makedirs(flags_dir, exist_ok=True)

    svg_path = os.path.join(flags_dir, "AEO.svg")
    svg = """<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"900\" height=\"600\" viewBox=\"0 0 900 600\">\n  <rect width=\"900\" height=\"600\" fill=\"#f8f6ed\"/>\n  <rect y=\"0\" width=\"900\" height=\"86\" fill=\"#f8b5c6\"/>\n  <rect y=\"86\" width=\"900\" height=\"86\" fill=\"#ffffff\"/>\n  <rect y=\"172\" width=\"900\" height=\"86\" fill=\"#f2c76e\"/>\n  <rect y=\"258\" width=\"900\" height=\"86\" fill=\"#ffffff\"/>\n  <rect y=\"344\" width=\"900\" height=\"86\" fill=\"#7bc7df\"/>\n  <rect y=\"430\" width=\"900\" height=\"86\" fill=\"#5a3a2a\"/>\n  <rect y=\"516\" width=\"900\" height=\"84\" fill=\"#111111\"/>\n  <g fill=\"#8a5a3c\" opacity=\"0.95\">\n    <ellipse cx=\"450\" cy=\"328\" rx=\"90\" ry=\"78\"/>\n    <ellipse cx=\"360\" cy=\"256\" rx=\"34\" ry=\"42\"/>\n    <ellipse cx=\"422\" cy=\"226\" rx=\"34\" ry=\"42\"/>\n    <ellipse cx=\"478\" cy=\"226\" rx=\"34\" ry=\"42\"/>\n    <ellipse cx=\"540\" cy=\"256\" rx=\"34\" ry=\"42\"/>\n  </g>\n  <text x=\"450\" y=\"560\" text-anchor=\"middle\" font-family=\"Verdana\" font-size=\"48\" fill=\"#ffffff\" font-weight=\"700\">AEO</text>\n</svg>\n"""

    with open(svg_path, "w", encoding="utf-8") as f:
        f.write(svg)

    print("[EXPORT] Custom flag written: Flags/AEO.svg")


# --------------------------------------------------------
# UNIQUE COLOR GENERATOR (no duplication possible)
# --------------------------------------------------------
def unique_color(used, step=16):
    while True:
        step = 20   # increase to 32 if needed

        r = random.randrange(0, 256, step)
        g = random.randrange(0, 256, step)
        b = random.randrange(0, 256, step)

        c = (r, g, b)
        if c not in used:
            used.add(c)
            return c

# --------------------------------------------------------
# EXPORT PROVINCE MAP (colors must NOT repeat)
# --------------------------------------------------------
def _draw_filled_coords(draw, coords, color):
    if not coords:
        return
    if len(coords) == 1:
        draw.point(coords[0], fill=color)
        return
    if len(coords) == 2:
        draw.line(coords, fill=color, width=1)
        return

    draw.polygon(coords, fill=color)


def _draw_polygon_with_holes(draw, poly, bounds, size, fill_color, hole_color=None):
    exterior_coords = geom_to_pixel_coords(poly, bounds, size)
    _draw_filled_coords(draw, exterior_coords, fill_color)

    if hole_color is None:
        return

    # Respect polygon interiors to prevent later-drawn containers from
    # swallowing already-drawn enclave/inner regions.
    for interior in poly.interiors:
        hole_coords = ring_to_pixel_coords(interior, bounds, size)
        _draw_filled_coords(draw, hole_coords, hole_color)


def _downsample_by_majority(img, factor=2, chunk_rows=512):
    if factor <= 1:
        return img

    arr = np.array(img, copy=False)
    h, w, _ = arr.shape
    h2 = (h // factor) * factor
    w2 = (w // factor) * factor
    if h2 == 0 or w2 == 0:
        return img

    arr = arr[:h2, :w2]
    out_h = h2 // factor
    out_w = w2 // factor
    out_keys = np.empty((out_h, out_w), dtype=np.int32)

    if factor != 2:
        # Safe fallback for non-2x: top-left pick per block.
        keys = (
            arr[:, :, 0].astype(np.int32)
            | (arr[:, :, 1].astype(np.int32) << 8)
            | (arr[:, :, 2].astype(np.int32) << 16)
        )
        out_keys[:, :] = keys[::factor, ::factor][:out_h, :out_w]
    else:
        for y0 in range(0, out_h, chunk_rows):
            y1 = min(out_h, y0 + chunk_rows)
            sub = arr[y0 * 2:y1 * 2, :, :]

            keys = (
                sub[:, :, 0].astype(np.int32)
                | (sub[:, :, 1].astype(np.int32) << 8)
                | (sub[:, :, 2].astype(np.int32) << 16)
            )
            blocks = (
                keys.reshape(y1 - y0, 2, out_w, 2)
                .transpose(0, 2, 1, 3)
                .reshape(y1 - y0, out_w, 4)
            )

            vals = blocks
            c0 = 1 + (vals[:, :, 0] == vals[:, :, 1]) + (vals[:, :, 0] == vals[:, :, 2]) + (vals[:, :, 0] == vals[:, :, 3])
            c1 = 1 + (vals[:, :, 1] == vals[:, :, 0]) + (vals[:, :, 1] == vals[:, :, 2]) + (vals[:, :, 1] == vals[:, :, 3])
            c2 = 1 + (vals[:, :, 2] == vals[:, :, 0]) + (vals[:, :, 2] == vals[:, :, 1]) + (vals[:, :, 2] == vals[:, :, 3])
            c3 = 1 + (vals[:, :, 3] == vals[:, :, 0]) + (vals[:, :, 3] == vals[:, :, 1]) + (vals[:, :, 3] == vals[:, :, 2])

            counts = np.stack((c0, c1, c2, c3), axis=2)
            pick = np.argmax(counts, axis=2)
            out_keys[y0:y1, :] = np.take_along_axis(vals, pick[:, :, None], axis=2)[:, :, 0]

    out = np.empty((out_h, out_w, 3), dtype=np.uint8)
    out[:, :, 0] = (out_keys & 255).astype(np.uint8)
    out[:, :, 1] = ((out_keys >> 8) & 255).astype(np.uint8)
    out[:, :, 2] = ((out_keys >> 16) & 255).astype(np.uint8)
    return Image.fromarray(out, mode="RGB")


def _remove_one_pixel_land_bridges(img, province_colors, pid_to_country, max_width_px=1):
    """
    Break visually fake narrow land bridges inside a province and
    reassign seam pixels to neighboring provinces.
    """
    max_width_px = max(1, int(max_width_px))
    open_iters = max(1, int(np.ceil(max_width_px / 2.0)))

    arr = np.array(img, copy=True)

    lut = np.full((256, 256, 256), -1, dtype=np.int32)
    pid_to_color = {}
    for color, pid in province_colors.items():
        r, g, b = color
        pid_i = int(pid)
        lut[r, g, b] = pid_i
        pid_to_color[pid_i] = np.array([r, g, b], dtype=np.uint8)

    pid_map = lut[arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]]
    original_pid_map = pid_map.copy()

    # 8-neighborhood opening with width-aware iterations removes narrow necks.
    kernel = np.ones((3, 3), dtype=np.uint8)
    moved_pixels = 0
    affected_provinces = 0

    pids = np.unique(pid_map[pid_map >= 0])
    total_pids = int(len(pids))
    for idx, pid in enumerate(pids, start=1):
        if idx == 1 or idx % 100 == 0 or idx == total_pids:
            print(f"[DEBUG] Thin-bridge cleanup progress: {idx}/{total_pids}")
        pid_i = int(pid)
        source_country = pid_to_country.get(pid_i)
        if not source_country:
            continue

        mask = pid_map == pid
        if int(np.sum(mask)) < 16:
            continue

        opened = ndi.binary_opening(mask, structure=kernel, iterations=open_iters)
        if not np.any(opened):
            continue

        core_labels, n_cores = ndi.label(opened, structure=kernel)
        if n_cores <= 1:
            continue

        # Partition original province pixels by nearest opened core.
        _, nearest_idx = ndi.distance_transform_edt(core_labels == 0, return_indices=True)
        assigned = core_labels[nearest_idx[0], nearest_idx[1]]
        assigned = assigned * mask

        up = np.zeros_like(assigned)
        down = np.zeros_like(assigned)
        left = np.zeros_like(assigned)
        right = np.zeros_like(assigned)
        up[1:, :] = assigned[:-1, :]
        down[:-1, :] = assigned[1:, :]
        left[:, 1:] = assigned[:, :-1]
        right[:, :-1] = assigned[:, 1:]

        seam = np.zeros_like(mask, dtype=bool)
        for nb in (up, down, left, right):
            seam |= (assigned > 0) & (nb > 0) & (assigned != nb)

        seam &= mask
        if not np.any(seam):
            continue

        province_changed = False
        ys, xs = np.where(seam)
        for y, x in zip(ys, xs):
            y0 = max(0, y - 1)
            y1 = min(pid_map.shape[0], y + 2)
            x0 = max(0, x - 1)
            x1 = min(pid_map.shape[1], x + 2)

            patch = pid_map[y0:y1, x0:x1].reshape(-1)
            candidates = patch[(patch >= 0) & (patch != pid)]
            if candidates.size == 0:
                continue

            same_country = np.array(
                [
                    int(c)
                    for c in candidates
                    if pid_to_country.get(int(c)) == source_country
                ],
                dtype=np.int32,
            )
            if same_country.size == 0:
                continue

            vals, cnts = np.unique(same_country, return_counts=True)
            target_pid = int(vals[np.argmax(cnts)])
            pid_map[y, x] = target_pid
            moved_pixels += 1
            province_changed = True

        if province_changed:
            affected_provinces += 1

    if moved_pixels <= 0:
        return Image.fromarray(arr, mode="RGB")

    changed = pid_map != original_pid_map
    changed_pids = np.unique(pid_map[changed])
    for pid in changed_pids:
        pid_i = int(pid)
        color = pid_to_color.get(pid_i)
        if color is None:
            continue
        arr[changed & (pid_map == pid_i)] = color

    print(
        f"[DEBUG] Thin-bridge cleanup ({max_width_px}px) moved pixels: "
        f"{moved_pixels} across provinces: {affected_provinces}"
    )

    return Image.fromarray(arr, mode="RGB")


def _despeckle_land_components(img, province_colors, pid_to_country, min_pixels=3):
    """Remove tiny isolated land-color components caused by raster artifacts."""
    arr = np.array(img, copy=True)
    h, w, _ = arr.shape
    structure = np.ones((3, 3), dtype=np.uint8)
    changed_pixels = 0

    lut = np.full((256, 256, 256), -1, dtype=np.int32)
    pid_to_color = {}
    for color, pid in province_colors.items():
        r, g, b = color
        pid_i = int(pid)
        lut[r, g, b] = pid_i
        pid_to_color[pid_i] = np.array([r, g, b], dtype=np.uint8)

    pid_map = lut[arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]]
    original_pid_map = pid_map.copy()

    items = list(province_colors.items())
    total_items = int(len(items))
    for idx, (color, pid) in enumerate(items, start=1):
        if idx == 1 or idx % 100 == 0 or idx == total_items:
            print(f"[DEBUG] Land despeckle progress: {idx}/{total_items}")
        pid_i = int(pid)
        source_country = pid_to_country.get(pid_i)
        if not source_country:
            continue

        mask = pid_map == pid_i
        if not mask.any():
            continue

        labels, n = ndi.label(mask, structure=structure)
        if n <= 1:
            continue

        counts = np.bincount(labels.ravel())
        small_labels = [lbl for lbl in range(1, len(counts)) if 0 < counts[lbl] < min_pixels]
        if not small_labels:
            continue

        for lbl in small_labels:
            ys, xs = np.where(labels == lbl)
            for y, x in zip(ys, xs):
                y0 = max(0, y - 1)
                y1 = min(h, y + 2)
                x0 = max(0, x - 1)
                x1 = min(w, x + 2)

                neighborhood = pid_map[y0:y1, x0:x1].reshape(-1)
                candidates = neighborhood[(neighborhood >= 0) & (neighborhood != pid_i)]
                if candidates.size == 0:
                    continue

                same_country = np.array(
                    [
                        int(c)
                        for c in candidates
                        if pid_to_country.get(int(c)) == source_country
                    ],
                    dtype=np.int32,
                )
                if same_country.size == 0:
                    continue

                vals, cnts = np.unique(same_country, return_counts=True)
                target_pid = int(vals[np.argmax(cnts)])
                pid_map[y, x] = target_pid
                changed_pixels += 1

    if changed_pixels > 0:
        changed = pid_map != original_pid_map
        changed_pids = np.unique(pid_map[changed])
        for pid in changed_pids:
            pid_i = int(pid)
            color = pid_to_color.get(pid_i)
            if color is None:
                continue
            arr[changed & (pid_map == pid_i)] = color

    if changed_pixels > 0:
        print(f"[DEBUG] Land despeckle changed pixels: {changed_pixels}")

    return Image.fromarray(arr, mode="RGB")


def _enforce_single_component_per_landmass(img, province_colors, pid_to_country, max_passes=3):
    """
    Ensure each province has at most one connected component per landmass.

    This keeps true islands untouched (different landmasses), while fixing
    split inland/mainland fragments of the same province color.
    """
    arr = np.array(img, copy=True)

    lut = np.full((256, 256, 256), -1, dtype=np.int32)
    pid_to_color = {}
    for color, pid in province_colors.items():
        r, g, b = color
        pid_i = int(pid)
        lut[r, g, b] = pid_i
        pid_to_color[pid_i] = np.array([r, g, b], dtype=np.uint8)

    pid_map = lut[arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]]
    original_pid_map = pid_map.copy()

    structure = np.ones((3, 3), dtype=np.uint8)
    landmass_labels, _ = ndi.label(pid_map >= 0, structure=structure)

    moved_components = 0
    moved_pixels = 0

    pids = np.unique(pid_map[pid_map >= 0])

    for pass_num in range(1, max_passes + 1):
        print(f"[DEBUG] Inland connectivity fix pass: {pass_num}/{max_passes}")
        pass_components = 0
        pass_pixels = 0

        total_pids = int(len(pids))
        for idx, pid in enumerate(pids, start=1):
            if idx == 1 or idx % 100 == 0 or idx == total_pids:
                print(f"[DEBUG] Inland connectivity progress: {idx}/{total_pids}")
            pid_i = int(pid)
            source_country = pid_to_country.get(pid_i)
            if not source_country:
                continue

            mask = pid_map == pid
            if not np.any(mask):
                continue

            labels, n = ndi.label(mask, structure=structure)
            if n <= 1:
                continue

            counts = np.bincount(labels.ravel())
            by_landmass = {}

            for lbl in range(1, n + 1):
                size = int(counts[lbl])
                if size <= 0:
                    continue

                ys, xs = np.where(labels == lbl)
                landmass_id = int(landmass_labels[ys[0], xs[0]])
                by_landmass.setdefault(landmass_id, []).append((lbl, size))

            labels_to_move = []
            for components in by_landmass.values():
                if len(components) <= 1:
                    continue

                components.sort(key=lambda t: t[1], reverse=True)
                for lbl, _size in components[1:]:
                    labels_to_move.append(lbl)

            if not labels_to_move:
                continue

            for lbl in labels_to_move:
                comp = labels == lbl
                dilated = ndi.binary_dilation(comp, structure=structure)
                border = dilated & (~comp)

                neighbor_ids = pid_map[border]
                neighbor_ids = neighbor_ids[(neighbor_ids >= 0) & (neighbor_ids != pid)]
                if neighbor_ids.size == 0:
                    continue

                same_country = np.array(
                    [
                        int(nid)
                        for nid in neighbor_ids
                        if pid_to_country.get(int(nid)) == source_country
                    ],
                    dtype=np.int32,
                )
                if same_country.size == 0:
                    continue

                vals, cnts = np.unique(same_country, return_counts=True)
                target_pid = int(vals[np.argmax(cnts)])

                pixels = int(np.sum(comp))
                pid_map[comp] = target_pid
                pass_components += 1
                pass_pixels += pixels

        moved_components += pass_components
        moved_pixels += pass_pixels

        if pass_components == 0:
            break

        # Province map changed after this pass, refresh pid list for next pass.
        pids = np.unique(pid_map[pid_map >= 0])

    if moved_pixels <= 0:
        return Image.fromarray(arr, mode="RGB")

    changed = pid_map != original_pid_map
    changed_pids = np.unique(pid_map[changed])
    for pid in changed_pids:
        pid_i = int(pid)
        color = pid_to_color.get(pid_i)
        if color is None:
            continue
        arr[changed & (pid_map == pid_i)] = color

    print(
        "[DEBUG] Inland connectivity fix moved components: "
        f"{moved_components}, pixels: {moved_pixels}"
    )

    return Image.fromarray(arr, mode="RGB")


def export_province_map(land, sea_regions):

    minx, miny, maxx, maxy = land.total_bounds
    bounds = (minx, miny, maxx, maxy)

    render_size = EXPORT_SIZE * max(int(PROVINCE_RENDER_SUPERSAMPLE), 1)

    img = Image.new("RGB", (render_size, render_size), SEA_COLOR)
    draw = ImageDraw.Draw(img)

    province_colors = {}
    used_colors = set()   # stores all used RGB colors
    pid_to_country = {int(pid): str(country) for pid, country in land["country"].items()}

    # -------------------------
    # SEA REGIONS (unique too)
    # Draw sea first so later land fills restore islands even when
    # the rasterized sea polygon ignores interior holes.
    # -------------------------
    sea_color_count = 0

    for region in sea_regions:
        color = unique_color(used_colors)
        sea_color_count += 1

        polys = [region] if region.geom_type == "Polygon" else region.geoms
        for poly in polys:
            _draw_polygon_with_holes(draw, poly, bounds, render_size, color, hole_color=None)

    print("[DEBUG] Sea regions:", sea_color_count)

    # -------------------------
    # LAND PROVINCES
    # -------------------------
    # Draw large provinces first and smaller/enclave provinces later.
    # This minimizes order-dependent overwrites along complex borders.
    land_order = sorted(
        land.index,
        key=lambda pid: float(land.loc[pid, "geometry"].area),
        reverse=True,
    )

    for pid in land_order:
        row = land.loc[pid]
        geom = row.geometry
        if geom.is_empty:
            continue

        color = unique_color(used_colors)
        province_colors[color] = pid

        polys = [geom] if geom.geom_type == "Polygon" else geom.geoms
        for poly in polys:
            _draw_polygon_with_holes(draw, poly, bounds, render_size, color, hole_color=SEA_COLOR)

    print("[DEBUG] Land provinces:", len(land))
    print("[DEBUG] Unique land colors:", len(province_colors))
    print("[DEBUG] Total unique colors:", len(used_colors))

    # Render at higher resolution then collapse by majority vote for cleaner borders.
    if render_size != EXPORT_SIZE:
        print(
            f"[DEBUG] Downsampling supersampled map: {render_size} -> {EXPORT_SIZE}"
        )
        img = _downsample_by_majority(img, factor=render_size // EXPORT_SIZE)

    # Remove 1-pixel internal bridges that make borders look hand-drawn/fake.
    print("[DEBUG] Starting thin-bridge cleanup...")
    img = _remove_one_pixel_land_bridges(
        img,
        province_colors,
        pid_to_country,
        max_width_px=THIN_BRIDGE_MAX_WIDTH_PX,
    )

    # Force one connected province piece per landmass (islands stay valid).
    print("[DEBUG] Starting inland connectivity fix...")
    img = _enforce_single_component_per_landmass(
        img,
        province_colors,
        pid_to_country,
        max_passes=3,
    )

    # Post-process tiny isolated land artifacts (single/few-pixel specks).
    print("[DEBUG] Starting land despeckle...")
    img = _despeckle_land_components(
        img,
        province_colors,
        pid_to_country,
        min_pixels=3,
    )

    # -------------------------
    # SAVE UNCOMPRESSED PNG
    # -------------------------
    img.save(
        os.path.join(OUT, "ProvinceMap.png"),
        format="PNG",
        optimize=False,
        compress_level=0,
        bits=8
    )

    return province_colors, bounds


# --------------------------------------------------------
# EXPORT ID MAP
# --------------------------------------------------------
def encode_province_id_rgb(pid):
    pid_i = int(pid)
    if pid_i < 0:
        raise ValueError("Province ID must be non-negative.")
    if pid_i > 0xFFFFFF:
        raise ValueError("Province ID exceeds 24-bit RGB encoding limit (16777215).")

    return (
        pid_i & 0xFF,
        (pid_i >> 8) & 0xFF,
        (pid_i >> 16) & 0xFF,
    )


def export_id_map(province_colors):

    img = Image.open(os.path.join(OUT, "ProvinceMap.png")).convert("RGB")
    arr = np.array(img)
    h, w, _ = arr.shape

    lut = np.full((256, 256, 256), -1, dtype=np.int32)

    for col, pid in province_colors.items():
        r, g, b = col
        lut[r, g, b] = pid

    id_map = np.full((h, w), -1, dtype=np.int32)
    sea_colors_in_order = []
    sea_seen = set()

    for y in range(h):
        for x in range(w):
            r, g, b = arr[y, x]
            pid = lut[r, g, b]
            id_map[y, x] = pid
            if pid < 0:
                col = (int(r), int(g), int(b))
                if col not in sea_seen:
                    sea_seen.add(col)
                    sea_colors_in_order.append(col)

    max_pid = int(id_map.max())
    base_sea_id = max_pid + 1
    sea_color_to_id = {
        col: base_sea_id + idx
        for idx, col in enumerate(sea_colors_in_order)
    }

    max_encoded_id = max(
        max_pid,
        max(sea_color_to_id.values()) if sea_color_to_id else -1,
    )
    if max_encoded_id > 0xFFFFFF:
        raise ValueError(
            f"Province ID {max_encoded_id} cannot be represented in 24-bit RGB mask."
        )

    # ID mask output (RGB encodes province ID directly).
    id_mask = Image.new("RGB", (w, h))
    px = id_mask.load()

    for y in range(h):
        for x in range(w):
            pid = id_map[y, x]
            if pid < 0:
                col = tuple(int(v) for v in arr[y, x])
                px[x, y] = encode_province_id_rgb(sea_color_to_id[col])
            else:
                px[x, y] = encode_province_id_rgb(pid)

    id_mask.save(os.path.join(OUT, "ProvinceIDMask.png"))
    # Backward-compatible alias used by existing runtime tools.
    id_mask.save(os.path.join(OUT, "ProvinceMask.png"))
    return id_map, sea_color_to_id


# --------------------------------------------------------
# EXPORT STATES
# --------------------------------------------------------
def export_states(land):
    states = sorted(land["country"].unique())

    with open(os.path.join(OUT, "States.txt"), "w") as f:
        for st in states:
            r = random.randint(20, 235)
            g = random.randint(20, 235)
            b = random.randint(20, 235)
            f.write(f"{st};{r};{g};{b}\n")


# --------------------------------------------------------
# EXPORT STATE FILES
# --------------------------------------------------------
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


# --------------------------------------------------------
# EXPORT PROVINCES.TXT
# --------------------------------------------------------
def _sanitize_txt_field(value):
    text = "" if value is None else str(value)
    return text.replace(";", ",").replace("\r", " ").replace("\n", " ").strip()


def _normalize_flag(value):
    if value is None:
        return 0
    if isinstance(value, (bool, np.bool_)):
        return int(value)
    if isinstance(value, (int, np.integer)):
        return 1 if int(value) != 0 else 0
    if isinstance(value, (float, np.floating)):
        return 1 if float(value) > 0 else 0

    text = str(value).strip().lower()
    if text in {"", "none", "nan", "-99", "0", "false", "no"}:
        return 0
    if text in {"1", "true", "yes"}:
        return 1

    try:
        return 1 if float(text) > 0 else 0
    except ValueError:
        return 0


def _clean_optional_text(value):
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"", "none", "nan"}:
        return ""
    return text


def _city_from_woe_label(value):
    text = _clean_optional_text(value)
    if not text:
        return ""
    return text.split(",", 1)[0].strip()


def _row_is_capital(land_row):
    explicit_flag = _normalize_flag(land_row.get("is_capital_province", 0))
    if explicit_flag:
        return 1

    for key in ("type_en", "type"):
        text = str(land_row.get(key) or "")
        if "capital" in text.lower():
            return 1

    return 0


def _build_country_capital_lookup(land):
    lookup = {}

    for _, row in land.iterrows():
        type_en = str(row.get("type_en") or "")
        type_raw = str(row.get("type") or "")
        if "capital" not in type_en.lower() and "capital" not in type_raw.lower():
            continue

        country = _clean_optional_text(row.get("country"))
        if not country or country in lookup:
            continue

        for key in ("capital_city_name", "woe_name"):
            city = _clean_optional_text(row.get(key))
            if city:
                lookup[country] = city
                break

        if country in lookup:
            continue

        city = _city_from_woe_label(row.get("woe_label"))
        if city:
            lookup[country] = city

    return lookup


def _row_capital_city_name(land_row, country_capitals):
    city = _clean_optional_text(land_row.get("capital_city_name"))
    if city:
        return city

    country = _clean_optional_text(land_row.get("country"))
    if country:
        city = _clean_optional_text(country_capitals.get(country))
        if city:
            return city

    for key in ("woe_name",):
        city = _clean_optional_text(land_row.get(key))
        if city:
            return city

    city = _city_from_woe_label(land_row.get("woe_label"))
    if city:
        return city

    for key in ("name_en", "name"):
        city = _clean_optional_text(land_row.get(key))
        if city:
            return city

    return ""


def _build_population_export_lookup(rows):
    lookup = {}
    for row in rows or []:
        pid = int(row.get("province_id") or 0)
        lookup[pid] = {
            "country_name": _sanitize_txt_field(row.get("country") or row.get("country_name") or ""),
            "population": int(row.get("population") or 0),
        }
    return lookup


def _build_gdp_export_lookup(rows):
    lookup = {}
    for row in rows or []:
        pid = int(row.get("province_id") or 0)
        lookup[pid] = {
            "gdp": float(row.get("gdp") or 0.0),
            "gdp_per_capita": float(row.get("gdp_per_capita") or 0.0),
        }
    return lookup


def _normalize_recruitable_ideology(value):
    ideology = canonical_ideology(value)
    if ideology == "kralostvi":
        return "kralovstvi"
    return ideology


def _compute_recruitable_population_value(population, ideology, is_capital):
    pop_value = max(int(population or 0), 0)
    ideology_key = _normalize_recruitable_ideology(ideology)
    share = RECRUITABLE_SHARE_BY_IDEOLOGY.get(ideology_key, DEFAULT_RECRUITABLE_SHARE)
    multiplier = CAPITAL_RECRUITABLE_MULTIPLIER if int(is_capital) else 1.0
    return int(round(pop_value * share * multiplier))


def _build_recruitable_population_lookup(
    land,
    population_rows=None,
    ideology_rows=None,
):
    population_by_pid = _build_population_export_lookup(population_rows)
    ideology_by_pid = {
        int(r["province_id"]): str(r.get("ideology") or "unknown")
        for r in (ideology_rows or [])
    }

    lookup = {}
    for pid, land_row in land.iterrows():
        pid_i = int(pid)
        pop = int(population_by_pid.get(pid_i, {}).get("population") or 0)
        ideology = ideology_by_pid.get(pid_i, "unknown")
        is_capital = _row_is_capital(land_row)
        lookup[pid_i] = _compute_recruitable_population_value(pop, ideology, is_capital)

    return lookup


def _rgb_tuple_to_key(color):
    r, g, b = color
    return int(r) | (int(g) << 8) | (int(b) << 16)


def _build_full_id_map_with_sea(id_map, province_rgb_map, sea_color_to_id):
    """Return an ID map where sea pixels are replaced by stable sea IDs."""
    full_map = id_map.astype(np.int32, copy=True)
    if not sea_color_to_id:
        return full_map

    sea_mask = full_map < 0
    if not np.any(sea_mask):
        return full_map

    key_to_id = {
        _rgb_tuple_to_key(color): int(sea_id)
        for color, sea_id in sea_color_to_id.items()
    }
    if not key_to_id:
        return full_map

    map_keys = np.array(sorted(key_to_id.keys()), dtype=np.int64)
    map_vals = np.array([key_to_id[k] for k in map_keys], dtype=np.int32)

    flat_full = full_map.reshape(-1)
    flat_sea_mask = sea_mask.reshape(-1)
    sea_indices = np.flatnonzero(flat_sea_mask)
    if sea_indices.size == 0:
        return full_map

    color_keys = (
        province_rgb_map[..., 0].astype(np.int64)
        | (province_rgb_map[..., 1].astype(np.int64) << 8)
        | (province_rgb_map[..., 2].astype(np.int64) << 16)
    )
    sea_keys = color_keys.reshape(-1)[sea_indices]

    idx = np.searchsorted(map_keys, sea_keys)
    in_range = idx < map_keys.size
    if np.any(in_range):
        in_range_idx = idx[in_range]
        matched = map_keys[in_range_idx] == sea_keys[in_range]
        if np.any(matched):
            target_indices = sea_indices[in_range][matched]
            flat_full[target_indices] = map_vals[in_range_idx[matched]]

    return full_map


def _build_neighbor_lookup(full_id_map):
    """Build undirected province adjacency from a full ID map."""
    neighbors = {}

    def register_pairs(a, b):
        diff = a != b
        if not np.any(diff):
            return

        left = a[diff].astype(np.int64)
        right = b[diff].astype(np.int64)
        valid = (left >= 0) & (right >= 0)
        if not np.any(valid):
            return

        left = left[valid]
        right = right[valid]
        p_min = np.minimum(left, right)
        p_max = np.maximum(left, right)
        pairs = np.unique(np.column_stack((p_min, p_max)), axis=0)

        for p1, p2 in pairs:
            i1 = int(p1)
            i2 = int(p2)
            neighbors.setdefault(i1, set()).add(i2)
            neighbors.setdefault(i2, set()).add(i1)

    register_pairs(full_id_map[:, :-1], full_id_map[:, 1:])
    register_pairs(full_id_map[:-1, :], full_id_map[1:, :])
    return {pid: sorted(ids) for pid, ids in neighbors.items()}


def export_provinces_txt(
    province_colors,
    id_map,
    land,
    population_rows=None,
    gdp_rows=None,
    sea_color_to_id=None,
    ideology_rows=None,
    recruitable_by_pid=None,
):

    out_path = os.path.join(OUT, "Provinces.txt")
    h, w = id_map.shape

    pid_to_color = {pid: col for col, pid in province_colors.items()}
    population_by_pid = _build_population_export_lookup(population_rows)
    gdp_by_pid = _build_gdp_export_lookup(gdp_rows)
    ideology_by_pid = {
        int(r["province_id"]): str(r.get("ideology") or "unknown")
        for r in (ideology_rows or [])
    }
    if recruitable_by_pid is None:
        recruitable_by_pid = _build_recruitable_population_lookup(
            land,
            population_rows=population_rows,
            ideology_rows=ideology_rows,
        )
    else:
        recruitable_by_pid = {
            int(pid): max(int(value or 0), 0)
            for pid, value in recruitable_by_pid.items()
        }

    rows = []
    country_capitals = _build_country_capital_lookup(land)

    max_pid = int(id_map.max())

    # SEA detection
    used_colors = set(pid_to_color.values())
    img = Image.open(os.path.join(OUT, "ProvinceMap.png")).convert("RGB")
    arr = np.array(img)

    if sea_color_to_id is None:
        sea_seen = {}
        for y in range(arr.shape[0]):
            for x in range(arr.shape[1]):
                col = tuple(int(v) for v in arr[y, x])
                if col not in used_colors and col not in sea_seen:
                    sea_seen[col] = len(sea_seen)

        base_sea_id = max_pid + 1
        sea_items = [
            (col, base_sea_id + idx)
            for idx, col in enumerate(sea_seen.keys())
        ]
    else:
        sea_items = sorted(sea_color_to_id.items(), key=lambda item: item[1])

    resolved_sea_color_to_id = {
        tuple(int(v) for v in col): int(sea_id)
        for col, sea_id in sea_items
    }
    full_id_map = _build_full_id_map_with_sea(id_map, arr, resolved_sea_color_to_id)
    neighbors_by_pid = _build_neighbor_lookup(full_id_map)

    for pid in range(max_pid + 1):
        if pid in pid_to_color:
            r, g, b = pid_to_color[pid]
            land_row = land.loc[pid]
            st = land_row["country"]
            typ = "land"
            owner = st
            controller = st
        else:
            continue

        province_name = _sanitize_txt_field(land_row.get("name_en") or land_row.get("name") or "")
        population_entry = population_by_pid.get(pid, {})
        gdp_entry = gdp_by_pid.get(pid, {})
        country_name = population_entry.get("country_name") or _sanitize_txt_field(land_row.get("admin") or st)
        population = int(population_entry.get("population") or 0)
        gdp_value = float(gdp_entry.get("gdp") or 0.0)
        gdp_per_capita = float(gdp_entry.get("gdp_per_capita") or 0.0)
        is_capital = _row_is_capital(land_row)
        capital_city = ""
        if is_capital:
            capital_city = _sanitize_txt_field(_row_capital_city_name(land_row, country_capitals))
        neighbor_ids = ",".join(str(n) for n in neighbors_by_pid.get(int(pid), []))
        ideology = ideology_by_pid.get(int(pid), "unknown")
        recruitable_population = int(recruitable_by_pid.get(int(pid), 0) or 0)

        ys, xs = np.where(id_map == pid)
        if len(xs) == 0:
            cx, cy = 0, 0
        else:
            cx = int(xs.mean())
            cy = int(ys.mean())

        rows.append(
            f"{pid};{r};{g};{b};{typ};{st};{owner};{controller};{cx};{cy};"
            f"{province_name};{country_name};{population};{gdp_value:.2f};{gdp_per_capita:.6f};"
            f"{is_capital};{capital_city};{neighbor_ids};{ideology};{recruitable_population}"
        )

    for col, sea_id in sea_items:
        r, g, b = col
        neighbor_ids = ",".join(str(n) for n in neighbors_by_pid.get(int(sea_id), []))
        rows.append(
            f"{sea_id};{r};{g};{b};sea;SEA;SEA;SEA;0;0;"
            f";SEA;0;0.00;0.000000;0;;{neighbor_ids};unknown;0"
        )

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(
            "id;R;G;B;type;state;owner;controller;x;y;"
            "province_name;country_name;population;gdp;gdp_per_capita;"
            "is_capital;capital_city;neighbors;ideology;recruitable_population\n"
        )
        for r in rows:
            f.write(r + "\n")

    print(f"[EXPORT] Provinces.txt written ({len(rows)} entries).")


def write_population_txt(rows, debug_rows, path):
    debug_map = {r["province_id"]: r for r in debug_rows}
    with open(path, "w", encoding="utf-8") as f:
        f.write("id;population;population_source;population_date;source_region;source_country;match_method\n")
        for r in rows:
            pid = r["province_id"]
            pop = r["population"] if r["population"] != "" else 0
            pop_date = r.get("population_date", "")
            source = r.get("population_source", "")
            d = debug_map.get(pid, {})
            f.write(
                f"{pid};{pop};{source};{pop_date};"
                f"{d.get('source_region','')};{d.get('source_country','')};{d.get('match_method','')}\n"
            )


def write_gdp_txt(rows, path):
    with open(path, "w", encoding="utf-8") as f:
        f.write("id;gdp;gdp_per_capita;gdp_source;gdp_year\n")
        for r in rows:
            pid = int(r.get("province_id") or 0)
            gdp_val = float(r.get("gdp") or 0.0)
            gdp_pc = float(r.get("gdp_per_capita") or 0.0)
            source = str(r.get("gdp_source") or "")
            year = r.get("gdp_year") or ""
            f.write(f"{pid};{gdp_val:.2f};{gdp_pc:.6f};{source};{year}\n")


def write_ideology_txt(rows, path):
    with open(path, "w", encoding="utf-8") as f:
        f.write("id;ideology;ideology_source;ideology_year\n")
        for r in rows:
            pid = int(r.get("province_id") or 0)
            ideology = str(r.get("ideology") or "unknown")
            source = str(r.get("ideology_source") or "")
            year = r.get("ideology_year") or ""
            f.write(f"{pid};{ideology};{source};{year}\n")


def write_relationships_txt(rows, path):
    with open(path, "w", encoding="utf-8") as f:
        f.write(
            "country_a;country_b;relationship_score;is_border;"
            "same_ideology;gdp_pc_ratio;relationship_source;relationship_year\n"
        )
        for r in rows:
            a = str(r.get("country_a") or "")
            b = str(r.get("country_b") or "")
            score = float(r.get("relationship_score") or 0.0)
            is_border = int(r.get("is_border") or 0)
            same_ideology = int(r.get("same_ideology") or 0)
            gdp_ratio = float(r.get("gdp_pc_ratio") or 0.0)
            source = str(r.get("relationship_source") or "")
            year = r.get("relationship_year") or ""
            f.write(
                f"{a};{b};{score:.2f};{is_border};{same_ideology};"
                f"{gdp_ratio:.6f};{source};{year}\n"
            )


def export_population_lookup_json(land, province_colors, rows, path):
    """
    Export a Godot-ready lookup file:
    - by_id: province id -> population + metadata
    - by_color: "R,G,B" -> province id
    """
    rows_by_pid = {
        int(r["province_id"]): r
        for r in rows
    }
    pid_to_color = {pid: col for col, pid in province_colors.items()}

    by_id = {}
    by_color = {}

    for pid, land_row in land.iterrows():
        pid_i = int(pid)
        pop_row = rows_by_pid.get(pid_i, {})
        r, g, b = pid_to_color.get(pid_i, (0, 0, 0))

        by_id[str(pid_i)] = {
            "province_id": pid_i,
            "province_name": str(land_row.get("name_en") or land_row.get("name") or ""),
            "country_iso3": str(land_row.get("country") or ""),
            "country_name": str(land_row.get("admin") or land_row.get("country") or ""),
            "population": int(pop_row.get("population") or 0),
            "population_source": str(pop_row.get("population_source") or ""),
            "population_date": str(pop_row.get("population_date") or ""),
            "color_rgb": [int(r), int(g), int(b)],
            "color_hex": f"#{int(r):02X}{int(g):02X}{int(b):02X}",
        }
        by_color[f"{int(r)},{int(g)},{int(b)}"] = pid_i

    payload = {
        "version": 1,
        "by_id": by_id,
        "by_color": by_color,
    }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    print(f"[EXPORT] ProvincePopulationLookup.json written ({len(by_id)} land provinces).")


# --------------------------------------------------------
# MAIN EXPORT
# --------------------------------------------------------
def run_export(land, sea_regions):
    print("[EXPORT] ProvinceMap...")
    province_colors, bounds = export_province_map(land, sea_regions)

    print("[EXPORT] ProvinceIDMask...")
    id_map, sea_color_to_id = export_id_map(province_colors)

    print("[EXPORT] PoliticalMap...")
    export_political_map(id_map, land, sea_regions, bounds)

    max_pid = int(id_map.max())
    print(f"[DEBUG] MAX PID DETECTED = {max_pid}")

    print("[EXPORT] Population CSV + map colors...")
    pop_values, rows, unmatched, debug_rows = generate_population_dataset(
        land,
        out_path=os.path.join(OUT, "Population.csv"),
        debug_path=os.path.join(OUT, "Population_debug.csv"),
    )
    if unmatched:
        print(f"[WARN] Population unmatched regions: {len(unmatched)} (showing up to 5)")
        for name, country in unmatched[:5]:
            safe_name = str(name).encode("ascii", "replace").decode("ascii")
            safe_country = str(country).encode("ascii", "replace").decode("ascii")
            print(f" - {safe_name} ({safe_country})")
    write_population_txt(rows, debug_rows, os.path.join(OUT, "Population.txt"))
    export_population_lookup_json(
        land,
        province_colors,
        rows,
        os.path.join(OUT, "ProvincePopulationLookup.json"),
    )

    pop_source_by_pid = {
        r["province_id"]: r.get("population_source", "")
        for r in rows
    }
    pop_country_by_pid = {
        r["province_id"]: r.get("country", "")
        for r in rows
    }

    land_areas = {
        pid: land.loc[pid].geometry.area / 1_000_000
        for pid in land.index
        if land.loc[pid].geometry.area > 0
    }

    print("[EXPORT] GDP CSV + map colors...")
    gdp_values, gdp_rows, gdp_missing = generate_gdp_dataset(
        land,
        population=pop_values,
        out_path=os.path.join(OUT, "GDP.csv"),
    )
    write_gdp_txt(gdp_rows, os.path.join(OUT, "GDP.txt"))
    if gdp_missing:
        print(f"[WARN] GDP missing for {len(gdp_missing)} countries (GDP set to 0 there).")

    print("[EXPORT] Ideology CSV + map colors...")
    ideology_values, ideology_rows, ideology_missing = generate_ideology_dataset(
        land,
        out_path=os.path.join(OUT, "Ideology.csv"),
    )
    write_ideology_txt(ideology_rows, os.path.join(OUT, "Ideology.txt"))
    if ideology_missing:
        print(
            f"[WARN] Ideology missing for {len(ideology_missing)} countries "
            "(set to unknown there)."
        )

    print("[EXPORT] Relationship CSV + map colors...")
    _country_relationship_index, _relationship_pairs, relationship_rows = generate_relationship_dataset(
        land,
        ideology_rows=ideology_rows,
        gdp_rows=gdp_rows,
        out_path=os.path.join(OUT, "Relationships.csv"),
        out_country_path=os.path.join(OUT, "CountryRelationships.csv"),
    )
    write_relationships_txt(relationship_rows, os.path.join(OUT, "Relationships.txt"))

    recruitable_values = _build_recruitable_population_lookup(
        land,
        population_rows=rows,
        ideology_rows=ideology_rows,
    )

    print("[EXPORT] Provinces.txt...")
    export_provinces_txt(
        province_colors,
        id_map,
        land,
        population_rows=rows,
        gdp_rows=gdp_rows,
        sea_color_to_id=sea_color_to_id,
        ideology_rows=ideology_rows,
        recruitable_by_pid=recruitable_values,
    )

    print("[EXPORT] GDP Map...")
    export_gdp_map(id_map, sea_regions, bounds, gdp=gdp_values, max_pid=max_pid)

    print("[EXPORT] Population Map...")
    export_population_map(
        id_map,
        sea_regions,
        bounds,
        population=pop_values,
        land_areas=land_areas,
        population_source=pop_source_by_pid,
        province_country=pop_country_by_pid,
        max_pid=max_pid,
    )

    print("[EXPORT] Ideology Map...")
    export_ideology_map(
        id_map,
        sea_regions,
        bounds,
        ideology_by_pid=ideology_values,
        max_pid=max_pid,
    )

    print("[EXPORT] Recruitable Population Map...")
    export_recruitable_population_map(
        id_map,
        sea_regions,
        bounds,
        recruitable_population=recruitable_values,
        max_pid=max_pid,
    )

    export_states(land)
    export_state_files(land)
    _write_custom_island_flag()

    print("[EXPORT] EXPORT COMPLETE")
