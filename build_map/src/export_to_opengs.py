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
    export_happiness_map,
    export_terrain_map,
    export_resources_map,
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
SEA_TO_SEA_MIN_SHARED_EDGES = 8
INLAND_SEA_MAX_ARTIFACT_PIXELS = 5000


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


def _despeckle_land_components(img, province_colors, pid_to_country, min_pixels=8):
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
                target_pid = None
                if candidates.size > 0:
                    same_country = np.array(
                        [
                            int(c)
                            for c in candidates
                            if pid_to_country.get(int(c)) == source_country
                        ],
                        dtype=np.int32,
                    )
                    if same_country.size > 0:
                        vals, cnts = np.unique(same_country, return_counts=True)
                        target_pid = int(vals[np.argmax(cnts)])

                if target_pid is None:
                    # If no same-country land is adjacent, this is a tiny detached
                    # sliver/islet artifact. Let the surrounding majority absorb it,
                    # including sea if needed.
                    sea_candidates = neighborhood[neighborhood < 0]
                    if sea_candidates.size > 0:
                        target_pid = -1
                    elif candidates.size > 0:
                        vals, cnts = np.unique(candidates.astype(np.int32), return_counts=True)
                        target_pid = int(vals[np.argmax(cnts)])
                    else:
                        continue

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


def _erase_tiny_global_land_artifacts(img, province_colors, max_pixels=2):
    arr = np.array(img, copy=True)

    lut = np.full((256, 256, 256), -1, dtype=np.int32)
    for color, pid in province_colors.items():
        r, g, b = color
        lut[r, g, b] = int(pid)

    pid_map = lut[arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]]
    land_mask = pid_map >= 0
    labels, n = ndi.label(land_mask, structure=np.ones((3, 3), dtype=np.uint8))
    if n <= 0:
        return img

    counts = np.bincount(labels.ravel())
    removed_components = 0
    removed_pixels = 0

    for lbl in range(1, len(counts)):
        size = int(counts[lbl])
        if size <= 0 or size > max_pixels:
            continue
        arr[labels == lbl] = np.array(SEA_COLOR, dtype=np.uint8)
        removed_components += 1
        removed_pixels += size

    if removed_pixels > 0:
        print(
            "[DEBUG] Global tiny land artifact cleanup removed components: "
            f"{removed_components}, pixels: {removed_pixels}"
        )

    return Image.fromarray(arr, mode="RGB")


def _erase_tiny_global_sea_artifacts(img, province_colors, max_pixels=2):
    arr = np.array(img, copy=True)

    lut = np.full((256, 256, 256), -1, dtype=np.int32)
    pid_to_color = {}
    for color, pid in province_colors.items():
        r, g, b = color
        pid_i = int(pid)
        lut[r, g, b] = pid_i
        pid_to_color[pid_i] = np.array([r, g, b], dtype=np.uint8)

    pid_map = lut[arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]]
    sea_mask = pid_map < 0
    labels, n = ndi.label(sea_mask, structure=np.ones((3, 3), dtype=np.uint8))
    if n <= 0:
        return img

    counts = np.bincount(labels.ravel())
    absorbed_components = 0
    absorbed_pixels = 0
    structure = np.ones((3, 3), dtype=np.uint8)

    for lbl in range(1, len(counts)):
        size = int(counts[lbl])
        if size <= 0 or size > max_pixels:
            continue

        comp = labels == lbl
        border = ndi.binary_dilation(comp, structure=structure) & (~comp)
        neighbor_ids = pid_map[border]
        neighbor_ids = neighbor_ids[neighbor_ids >= 0]
        if neighbor_ids.size == 0:
            continue

        vals, cnts = np.unique(neighbor_ids.astype(np.int32), return_counts=True)
        target_pid = int(vals[np.argmax(cnts)])
        color = pid_to_color.get(target_pid)
        if color is None:
            continue

        arr[comp] = color
        absorbed_components += 1
        absorbed_pixels += size

    if absorbed_pixels > 0:
        print(
            "[DEBUG] Global tiny sea artifact cleanup absorbed components: "
            f"{absorbed_components}, pixels: {absorbed_pixels}"
        )

    return Image.fromarray(arr, mode="RGB")


def _erase_inland_sea_components(img, province_colors):
    """Remove sea components not touching the map edge by recolouring them with
    the most common adjacent land province.

    Only small enclosed components are removed, so legitimate enclosed seas
    (for example the Black Sea) are preserved.

    Uses a fully vectorised border scan (4-neighbour shifts) instead of
    per-label dilation, so it runs in O(H*W).
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
    sea_mask = pid_map < 0

    labels, n = ndi.label(sea_mask, structure=np.ones((3, 3), dtype=np.uint8))
    if n <= 0:
        return img

    counts = np.bincount(labels.ravel())

    # Which labels touch the map border? — O(border pixels only)
    border_labels = set()
    border_labels.update(labels[0, :].tolist())
    border_labels.update(labels[-1, :].tolist())
    border_labels.update(labels[:, 0].tolist())
    border_labels.update(labels[:, -1].tolist())
    border_labels.discard(0)

    inland_labels = [
        lbl
        for lbl in range(1, n + 1)
        if lbl not in border_labels and int(counts[lbl]) <= INLAND_SEA_MAX_ARTIFACT_PIXELS
    ]
    if not inland_labels:
        return img

    inland_label_set = set(inland_labels)

    # Build adjacency: for every adjacent (sea, land) pair, accumulate the
    # land pid keyed by sea label.  Done with 4 vectorised shift operations.
    label_to_land_votes = {}  # lbl -> Counter of land pids

    def _accumulate(sea_lbl_row, land_pid_row):
        sea_inland = np.isin(sea_lbl_row, inland_labels)
        if not sea_inland.any():
            return
        sl = sea_lbl_row[sea_inland]
        lp = land_pid_row[sea_inland]
        valid = lp >= 0
        for lbl, lpid in zip(sl[valid], lp[valid]):
            lbl_i = int(lbl)
            lpid_i = int(lpid)
            entry = label_to_land_votes.setdefault(lbl_i, {})
            entry[lpid_i] = entry.get(lpid_i, 0) + 1

    # Horizontal neighbours
    _accumulate(labels[:, :-1].ravel(), pid_map[:, 1:].ravel())
    _accumulate(labels[:, 1:].ravel(), pid_map[:, :-1].ravel())
    # Vertical neighbours
    _accumulate(labels[:-1, :].ravel(), pid_map[1:, :].ravel())
    _accumulate(labels[1:, :].ravel(), pid_map[:-1, :].ravel())

    # Apply recolour
    removed_components = 0
    removed_pixels = 0
    skipped_large_enclosed_components = 0
    skipped_large_enclosed_pixels = 0

    for lbl in range(1, n + 1):
        if lbl in border_labels:
            continue
        if lbl in inland_label_set:
            continue
        size = int(counts[lbl])
        if size > INLAND_SEA_MAX_ARTIFACT_PIXELS:
            skipped_large_enclosed_components += 1
            skipped_large_enclosed_pixels += size

    for lbl in inland_labels:
        votes = label_to_land_votes.get(lbl)
        if not votes:
            continue
        target_pid = max(votes, key=votes.get)
        color = pid_to_color.get(int(target_pid))
        if color is None:
            continue
        mask = labels == lbl
        arr[mask] = color
        removed_components += 1
        removed_pixels += int(counts[lbl])

    if removed_pixels > 0:
        print(
            "[DEBUG] Inland sea cleanup removed components: "
            f"{removed_components}, pixels: {removed_pixels}"
        )

    if skipped_large_enclosed_components > 0:
        print(
            "[DEBUG] Inland sea cleanup preserved enclosed sea components: "
            f"{skipped_large_enclosed_components}, "
            f"pixels: {skipped_large_enclosed_pixels}, "
            f"threshold: {INLAND_SEA_MAX_ARTIFACT_PIXELS}"
        )

    return Image.fromarray(arr, mode="RGB")


def export_province_map(land, sea_regions):

    # Keep export bounds tied to base Europe, not decorative custom islands.
    bounds_land = land
    if "country" in land.columns:
        base_land = land[land["country"] != "AEO"]
        if len(base_land) > 0:
            bounds_land = base_land

    minx, miny, maxx, maxy = bounds_land.total_bounds
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
        polys = [region] if region.geom_type == "Polygon" else region.geoms
        for poly in polys:
            if poly.is_empty:
                continue
            # Assign one sea province color per connected polygon piece.
            # Using one color for the whole MultiPolygon causes one sea ID to span
            # disconnected basins and creates unrealistic neighbor relationships.
            color = unique_color(used_colors)
            sea_color_count += 1
            _draw_polygon_with_holes(draw, poly, bounds, render_size, color, hole_color=None)

    print("[DEBUG] Sea provinces (connected pieces):", sea_color_count)

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
        min_pixels=8,
    )

    img = _erase_tiny_global_land_artifacts(img, province_colors, max_pixels=2)
    img = _erase_tiny_global_sea_artifacts(img, province_colors, max_pixels=2)
    img = _erase_inland_sea_components(img, province_colors)

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
    os.makedirs(folder, exist_ok=True)

    # Remove stale state files so removed countries do not linger in exports.
    for name in os.listdir(folder):
        if not name.lower().endswith(".txt"):
            continue
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            os.remove(path)

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


def _remove_legacy_custom_flag_artifact():
    legacy_flag = os.path.join(OUT, "Flags", "AEO.svg")
    if os.path.isfile(legacy_flag):
        os.remove(legacy_flag)
        print("[EXPORT] Removed legacy flag artifact: Flags/AEO.svg")


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


def _normalize_happiness_ideology(value):
    ideology = canonical_ideology(value)
    if ideology == "kralostvi":
        return "kralovstvi"
    return ideology


def _build_happiness_lookup(land, gdp_rows=None, ideology_rows=None):
    """Build province happiness score (0..100), currently country-level and copied to provinces."""
    country_gdp_pc = {}
    for row in gdp_rows or []:
        country = str(row.get("country_iso3") or "").strip().upper()
        if not country:
            continue

        gdp_pc = float(row.get("gdp_per_capita") or 0.0)
        if gdp_pc > 0:
            country_gdp_pc[country] = gdp_pc

    ideology_counts = {}
    for row in ideology_rows or []:
        country = str(row.get("country_iso3") or "").strip().upper()
        if not country:
            continue

        ideology = _normalize_happiness_ideology(row.get("ideology"))
        ideology_counts.setdefault(country, {})
        ideology_counts[country][ideology] = ideology_counts[country].get(ideology, 0) + 1

    country_ideology = {}
    for country, counts in ideology_counts.items():
        country_ideology[country] = max(counts.items(), key=lambda x: x[1])[0]

    gdp_values = list(country_gdp_pc.values())
    gdp_min = min(gdp_values) if gdp_values else 0.0
    gdp_max = max(gdp_values) if gdp_values else 0.0
    gdp_span = gdp_max - gdp_min

    ideology_bonus = {
        "demokracie": 20,
        "kralovstvi": 10,
        "autokracie": -10,
        "unknown": 0,
    }

    country_happiness = {}
    for country in set(list(country_gdp_pc.keys()) + list(country_ideology.keys())):
        gdp_pc = country_gdp_pc.get(country, 0.0)
        if gdp_span > 0 and gdp_pc > 0:
            gdp_score = int(round(30.0 * ((gdp_pc - gdp_min) / gdp_span)))
        else:
            gdp_score = 15

        ideology = country_ideology.get(country, "unknown")
        score = 40 + ideology_bonus.get(ideology, 0) + gdp_score
        country_happiness[country] = max(0, min(100, int(round(score))))

    province_happiness = {}
    for pid, row in land.iterrows():
        pid_i = int(pid)
        country = str(row.get("country") or "").strip().upper()
        province_happiness[pid_i] = country_happiness.get(country, 50)

    return province_happiness


TERRAIN_INDEX = {
    "sea": 0,
    "city": 1,
    "plains": 2,
    "forest": 3,
    "hills": 4,
    "mountains": 5,
}


RESOURCE_INDEX = {
    "none": 0,
    "grain": 1,
    "timber": 2,
    "iron": 3,
    "coal": 4,
    "oil": 5,
    "gas": 6,
    "gold": 7,
    "uranium": 8,
}


def _terrain_from_name(name_text):
    text = str(name_text or "").lower()
    mountain_markers = (
        "alps",
        "alpine",
        "mount",
        "mountain",
        "berg",
        "highland",
        "pyren",
        "carpath",
        "tatra",
        "sierra",
        "dinar",
        "jura",
        "balkan",
    )
    forest_markers = (
        "forest",
        "wood",
        "wald",
        "taiga",
        "boreal",
    )

    if any(marker in text for marker in mountain_markers):
        return "mountains"
    if any(marker in text for marker in forest_markers):
        return "forest"
    return ""


def _build_terrain_lookup(land, population_rows=None):
    """Build terrain category per province with deterministic heuristics."""
    population_by_pid = _build_population_export_lookup(population_rows)
    terrain_by_pid = {}

    for pid, land_row in land.iterrows():
        pid_i = int(pid)
        population = int(population_by_pid.get(pid_i, {}).get("population") or 0)
        area_km2 = float(land_row.geometry.area / 1_000_000) if land_row.geometry is not None else 0.0
        density = (population / area_km2) if area_km2 > 0 else 0.0

        province_name = str(land_row.get("name_en") or land_row.get("name") or "")
        type_name = str(land_row.get("type_en") or land_row.get("type") or "")
        from_name = _terrain_from_name(f"{province_name} {type_name}")

        if _row_is_capital(land_row) or density >= 1200:
            terrain = "city"
        elif from_name:
            terrain = from_name
        elif density <= 35 and area_km2 >= 12000:
            terrain = "forest"
        elif density <= 120:
            terrain = "hills"
        else:
            terrain = "plains"

        terrain_by_pid[pid_i] = terrain

    return terrain_by_pid


def _build_resource_lookup(
    land,
    population_rows=None,
    gdp_rows=None,
    terrain_by_pid=None,
):
    """Build deterministic resource deposits per province."""
    population_by_pid = _build_population_export_lookup(population_rows)
    gdp_by_pid = _build_gdp_export_lookup(gdp_rows)
    if terrain_by_pid is None:
        terrain_by_pid = _build_terrain_lookup(land, population_rows=population_rows)

    base_amount = {
        "grain": 45,
        "timber": 50,
        "iron": 42,
        "coal": 40,
        "oil": 32,
        "gas": 30,
        "gold": 18,
        "uranium": 12,
        "none": 0,
    }

    resources_by_pid = {}

    for pid, land_row in land.iterrows():
        pid_i = int(pid)
        terrain = str(terrain_by_pid.get(pid_i, "plains") or "plains").strip().lower()
        pop = int(population_by_pid.get(pid_i, {}).get("population") or 0)
        gdp_pc = float(gdp_by_pid.get(pid_i, {}).get("gdp_per_capita") or 0.0)

        rng = random.Random((pid_i + 1) * 977)
        roll = rng.random()

        if terrain == "forest":
            resource_type = "timber"
        elif terrain == "mountains":
            if roll < 0.45:
                resource_type = "iron"
            elif roll < 0.75:
                resource_type = "coal"
            elif roll < 0.92:
                resource_type = "gold"
            else:
                resource_type = "uranium"
        elif terrain == "hills":
            if roll < 0.45:
                resource_type = "iron"
            elif roll < 0.75:
                resource_type = "coal"
            else:
                resource_type = "grain"
        elif terrain == "city":
            if roll < 0.40:
                resource_type = "coal"
            elif roll < 0.70:
                resource_type = "iron"
            elif roll < 0.90:
                resource_type = "gas"
            else:
                resource_type = "oil"
        else:
            if roll < 0.62:
                resource_type = "grain"
            elif roll < 0.80:
                resource_type = "oil"
            elif roll < 0.93:
                resource_type = "gas"
            else:
                resource_type = "iron"

        pop_bonus = min(20, int(round(np.log10(max(pop, 1)) * 3.0)))
        gdp_bonus = min(15, int(round((gdp_pc * 1_000_000.0) / 6.0)))
        terrain_bonus = {
            "mountains": 8,
            "hills": 4,
            "forest": 5,
            "plains": 2,
            "city": 1,
        }.get(terrain, 2)
        jitter = rng.randint(-6, 6)

        amount = base_amount.get(resource_type, 0) + pop_bonus + gdp_bonus + terrain_bonus + jitter
        amount = max(1, min(100, int(amount)))

        resources_by_pid[pid_i] = {
            "resource_type": resource_type,
            "resource_index": RESOURCE_INDEX.get(resource_type, 0),
            "resource_amount": amount,
        }

    return resources_by_pid


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


def _build_neighbor_lookup(
    full_id_map,
    sea_ids=None,
    sea_to_sea_min_shared_edges=1,
    return_pair_counts=False,
):
    """Build undirected province adjacency from a full ID map."""
    neighbors = {}
    pair_counts = {}
    sea_ids = {int(pid) for pid in (sea_ids or set())}

    def count_pairs(a, b):
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
        pairs = np.column_stack((p_min, p_max))

        unique_pairs, counts = np.unique(pairs, axis=0, return_counts=True)
        for (p1, p2), count in zip(unique_pairs, counts):
            key = (int(p1), int(p2))
            pair_counts[key] = pair_counts.get(key, 0) + int(count)

    count_pairs(full_id_map[:, :-1], full_id_map[:, 1:])
    count_pairs(full_id_map[:-1, :], full_id_map[1:, :])

    for (i1, i2), count in pair_counts.items():
        if i1 in sea_ids and i2 in sea_ids and count < sea_to_sea_min_shared_edges:
            continue
        neighbors.setdefault(i1, set()).add(i2)
        neighbors.setdefault(i2, set()).add(i1)

    neighbor_lookup = {pid: sorted(ids) for pid, ids in neighbors.items()}
    if return_pair_counts:
        return neighbor_lookup, pair_counts
    return neighbor_lookup


def _compute_pid_anchor(full_id_map, pid):
    ys, xs = np.where(full_id_map == int(pid))
    if len(xs) == 0:
        return 0, 0

    cx = int(xs.mean())
    cy = int(ys.mean())
    if full_id_map[cy, cx] == int(pid):
        return cx, cy

    distances = (xs - cx) ** 2 + (ys - cy) ** 2
    best_idx = int(np.argmin(distances))
    return int(xs[best_idx]), int(ys[best_idx])


def _sea_anchor_line_crosses_land(full_id_map, pid_a, pid_b, anchors_by_pid, max_land_pixels=8):
    ax, ay = anchors_by_pid.get(int(pid_a), (0, 0))
    bx, by = anchors_by_pid.get(int(pid_b), (0, 0))

    steps = max(abs(bx - ax), abs(by - ay), 1) + 1
    xs = np.rint(np.linspace(ax, bx, steps)).astype(np.int32)
    ys = np.rint(np.linspace(ay, by, steps)).astype(np.int32)
    xs = np.clip(xs, 0, full_id_map.shape[1] - 1)
    ys = np.clip(ys, 0, full_id_map.shape[0] - 1)

    vals = full_id_map[ys, xs]
    land_hits = (vals >= 0) & (vals != int(pid_a)) & (vals != int(pid_b))
    return int(np.count_nonzero(land_hits)) > int(max_land_pixels)


def export_provinces_txt(
    province_colors,
    id_map,
    land,
    population_rows=None,
    gdp_rows=None,
    sea_color_to_id=None,
    ideology_rows=None,
    recruitable_by_pid=None,
    happiness_by_pid=None,
    terrain_by_pid=None,
    resources_by_pid=None,
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

    if happiness_by_pid is None:
        happiness_by_pid = _build_happiness_lookup(
            land,
            gdp_rows=gdp_rows,
            ideology_rows=ideology_rows,
        )
    else:
        happiness_by_pid = {
            int(pid): max(0, min(100, int(value or 0)))
            for pid, value in happiness_by_pid.items()
        }

    if terrain_by_pid is None:
        terrain_by_pid = _build_terrain_lookup(
            land,
            population_rows=population_rows,
        )
    else:
        terrain_by_pid = {
            int(pid): str(value or "plains").strip().lower()
            for pid, value in terrain_by_pid.items()
        }

    if resources_by_pid is None:
        resources_by_pid = _build_resource_lookup(
            land,
            population_rows=population_rows,
            gdp_rows=gdp_rows,
            terrain_by_pid=terrain_by_pid,
        )
    else:
        norm_resources = {}
        for pid, value in resources_by_pid.items():
            pid_i = int(pid)
            record = value or {}
            resource_type = str(record.get("resource_type") or "none").strip().lower()
            resource_index = RESOURCE_INDEX.get(resource_type, 0)
            resource_amount = max(0, min(100, int(record.get("resource_amount") or 0)))
            norm_resources[pid_i] = {
                "resource_type": resource_type,
                "resource_index": resource_index,
                "resource_amount": resource_amount,
            }
        resources_by_pid = norm_resources

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
    
    # DEBUG: Check if there are any unmapped sea pixels (ID = -1)
    unmapped_sea_pixels = np.sum(full_id_map < 0)
    if unmapped_sea_pixels > 0:
        print(f"[WARNING] {unmapped_sea_pixels} sea pixels remained unmapped after sea ID assignment!")
        print(f"[WARNING] This may cause provinces touching this unmapped sea to have missing neighbors.")
    
    valid_sea_ids = {int(s_id) for _, s_id in sea_items}
    valid_land_ids = set(pid_to_color.keys())
    neighbors_by_pid, pair_counts = _build_neighbor_lookup(
        full_id_map,
        sea_ids=valid_sea_ids,
        sea_to_sea_min_shared_edges=SEA_TO_SEA_MIN_SHARED_EDGES,
        return_pair_counts=True,
    )

    # Build neighbor lookup once from the full map and export direct neighbors
    # for both land and sea rows. Some runtimes evaluate coastal checks from
    # either side, so adjacency must remain bidirectional across land/sea.

    # Landlocked countries should never have sea adjacency (sanity check post-fix).
    LANDLOCKED_COUNTRIES = {"AUT", "HUN", "SVK", "CZE", "CHE", "LUX", "BLR", "MDA", "SRB", "MKD"}
    landlocked_pids = set()
    for pid, land_row in land.iterrows():
        if isinstance(pid, int) and land_row.get("country") in LANDLOCKED_COUNTRIES:
            landlocked_pids.add(pid)

    # Remove sea adjacency from landlocked provinces.
    for pid in landlocked_pids:
        if pid in neighbors_by_pid:
            neighbors_by_pid[pid] = [n for n in neighbors_by_pid[pid] if n not in valid_sea_ids]

    # Sea movement is rendered using province anchor points. If a direct sea-to-sea
    # edge would send the anchor-to-anchor segment across land, drop that edge.
    sea_anchor_by_pid = {
        int(sea_id): _compute_pid_anchor(full_id_map, int(sea_id))
        for _, sea_id in sea_items
    }
    blocked_sea_edges = 0
    for sea_id in list(valid_sea_ids):
        sea_neighbors = list(neighbors_by_pid.get(sea_id, []))
        for neighbor_id in sea_neighbors:
            if neighbor_id <= sea_id or neighbor_id not in valid_sea_ids:
                continue
            if _sea_anchor_line_crosses_land(full_id_map, sea_id, neighbor_id, sea_anchor_by_pid):
                neighbors_by_pid[sea_id] = [n for n in neighbors_by_pid.get(sea_id, []) if n != neighbor_id]
                neighbors_by_pid[neighbor_id] = [n for n in neighbors_by_pid.get(neighbor_id, []) if n != sea_id]
                blocked_sea_edges += 1

    if blocked_sea_edges > 0:
        print(f"[DEBUG] Blocked sea edges crossing land: {blocked_sea_edges}")

    # Fallback: if a sea province ends up with zero sea neighbors after filtering,
    # restore the strongest original sea contact (by shared-edge count) when safe.
    restored_isolated_sea_edges = 0
    restored_isolated_sea_edges_nearest = 0

    def _add_bidirectional_sea_edge(pid_a, pid_b):
        neighbors_by_pid.setdefault(pid_a, [])
        neighbors_by_pid.setdefault(pid_b, [])
        if pid_b not in neighbors_by_pid[pid_a]:
            neighbors_by_pid[pid_a].append(pid_b)
        if pid_a not in neighbors_by_pid[pid_b]:
            neighbors_by_pid[pid_b].append(pid_a)
        neighbors_by_pid[pid_a] = sorted(set(neighbors_by_pid[pid_a]))
        neighbors_by_pid[pid_b] = sorted(set(neighbors_by_pid[pid_b]))

    for sea_id in sorted(valid_sea_ids):
        current_sea_neighbors = [
            n for n in neighbors_by_pid.get(sea_id, []) if n in valid_sea_ids
        ]
        if current_sea_neighbors:
            continue

        # 1) Prefer restoring strongest original touching sea edge.
        candidates = []
        for (a, b), count in pair_counts.items():
            if a == sea_id and b in valid_sea_ids:
                candidates.append((b, int(count)))
            elif b == sea_id and a in valid_sea_ids:
                candidates.append((a, int(count)))

        candidates.sort(key=lambda item: item[1], reverse=True)
        restored = False
        for candidate_id, _shared_edges in candidates:
            if _sea_anchor_line_crosses_land(
                full_id_map,
                sea_id,
                candidate_id,
                sea_anchor_by_pid,
            ):
                continue
            _add_bidirectional_sea_edge(sea_id, candidate_id)
            restored_isolated_sea_edges += 1
            restored = True
            break

        if restored:
            continue

        # 2) If no touching edge survives, connect to nearest legal sea province.
        ax, ay = sea_anchor_by_pid.get(sea_id, (0, 0))
        nearest_candidates = []
        for other_id in valid_sea_ids:
            if other_id == sea_id:
                continue
            bx, by = sea_anchor_by_pid.get(other_id, (0, 0))
            dist2 = (ax - bx) * (ax - bx) + (ay - by) * (ay - by)
            nearest_candidates.append((dist2, other_id))

        nearest_candidates.sort(key=lambda item: item[0])
        for _dist2, candidate_id in nearest_candidates:
            if _sea_anchor_line_crosses_land(
                full_id_map,
                sea_id,
                candidate_id,
                sea_anchor_by_pid,
                max_land_pixels=40,
            ):
                continue
            _add_bidirectional_sea_edge(sea_id, candidate_id)
            restored_isolated_sea_edges_nearest += 1
            break

    if restored_isolated_sea_edges > 0 or restored_isolated_sea_edges_nearest > 0:
        print(
            "[DEBUG] Restored isolated sea edges: "
            f"touching={restored_isolated_sea_edges}, "
            f"nearest={restored_isolated_sea_edges_nearest}"
        )

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
        # Keep all direct neighbors so coastal checks can use this field directly.
        all_neighbors = neighbors_by_pid.get(int(pid), [])
        valid_neighbors = [n for n in all_neighbors if n in valid_land_ids or n in valid_sea_ids]
        neighbor_ids = ",".join(str(n) for n in valid_neighbors)
        ideology = ideology_by_pid.get(int(pid), "unknown")
        recruitable_population = int(recruitable_by_pid.get(int(pid), 0) or 0)
        happiness = int(happiness_by_pid.get(int(pid), 50) or 50)
        terrain = terrain_by_pid.get(int(pid), "plains")
        terrain_index = TERRAIN_INDEX.get(terrain, TERRAIN_INDEX["plains"])
        resource_entry = resources_by_pid.get(int(pid), {})
        resource_type = str(resource_entry.get("resource_type") or "none")
        resource_index = int(resource_entry.get("resource_index") or RESOURCE_INDEX["none"])
        resource_amount = int(resource_entry.get("resource_amount") or 0)

        ys, xs = np.where(id_map == pid)
        if len(xs) == 0:
            cx, cy = 0, 0
        else:
            cx = int(xs.mean())
            cy = int(ys.mean())

        rows.append(
            f"{pid};{r};{g};{b};{typ};{st};{owner};{controller};{cx};{cy};"
            f"{province_name};{country_name};{population};{gdp_value:.2f};{gdp_per_capita:.6f};"
            f"{is_capital};{capital_city};{neighbor_ids};{ideology};{recruitable_population};{happiness};"
            f"{terrain};{terrain_index};{resource_type};{resource_index};{resource_amount}"
        )

    for col, sea_id in sea_items:
        r, g, b = col
        # Keep all direct neighbors for sea rows as well (includes bordering land).
        all_neighbors = neighbors_by_pid.get(int(sea_id), [])
        valid_neighbors = [n for n in all_neighbors if n in valid_land_ids or n in valid_sea_ids]
        neighbor_ids = ",".join(str(n) for n in valid_neighbors)

        # Preserve usable navigation geometry for sea provinces as well.
        # Some runtime pathfinders use x/y as heuristic input.
        ys, xs = np.where(full_id_map == int(sea_id))
        if len(xs) == 0:
            cx, cy = 0, 0
        else:
            cx = int(xs.mean())
            cy = int(ys.mean())

        rows.append(
            f"{sea_id};{r};{g};{b};sea;SEA;SEA;SEA;{cx};{cy};"
            f";SEA;0;0.00;0.000000;0;;{neighbor_ids};unknown;0;0;sea;0;none;0;0"
        )

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(
            "id;R;G;B;type;state;owner;controller;x;y;"
            "province_name;country_name;population;gdp;gdp_per_capita;"
            "is_capital;capital_city;neighbors;ideology;recruitable_population;happiness;"
            "terrain;terrain_index;resource_type;resource_index;resource_amount\n"
        )
        for r in rows:
            f.write(r + "\n")

    # Debug output: check for provinces with no neighbors or invalid neighbors
    provinces_without_neighbors = []
    provinces_with_invalid_neighbors = []
    orphaned_provinces = []
    
    # Build set of all province IDs that were written to Provinces.txt
    all_pids = set()
    for r in rows:
        fields = r.split(";")
        pid = int(fields[0])
        all_pids.add(pid)
    
    # Check for orphaned provinces (in neighbors_by_pid but not in rows)
    for pid_in_neighbors in neighbors_by_pid.keys():
        if pid_in_neighbors not in all_pids:
            orphaned_provinces.append(pid_in_neighbors)
    
    for r in rows:
        fields = r.split(";")
        pid = int(fields[0])
        ptype = fields[4]
        neighbors_str = fields[17]
        
        if not neighbors_str.strip():
            if ptype == "land":
                provinces_without_neighbors.append(pid)
        else:
            neighbors = [int(n) for n in neighbors_str.split(",") if n.strip()]
            invalid = [n for n in neighbors if n not in all_pids]
            if invalid:
                provinces_with_invalid_neighbors.append((pid, invalid))
    
    if orphaned_provinces:
        print(f"[ERROR] {len(orphaned_provinces)} ORPHANED provinces in neighbors but NOT in Provinces.txt: {orphaned_provinces[:20]}...")
    
    if provinces_without_neighbors:
        print(f"[WARNING] {len(provinces_without_neighbors)} land provinces with NO neighbors: {provinces_without_neighbors[:20]}...")
    
    if provinces_with_invalid_neighbors:
        print(f"[WARNING] {len(provinces_with_invalid_neighbors)} provinces with invalid neighbor references:")
        for pid, invalid in provinces_with_invalid_neighbors[:10]:
            print(f"  Province {pid} references invalid neighbors: {invalid}")
    
    if not orphaned_provinces and not provinces_without_neighbors and not provinces_with_invalid_neighbors:
        print(f"[OK] All neighbors are valid - no orphaned or invalid references detected.")
    
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


def write_resources_csv(resources_by_pid, path):
    with open(path, "w", encoding="utf-8") as f:
        f.write("province_id;resource_type;resource_index;resource_amount\n")
        for pid in sorted(resources_by_pid.keys()):
            record = resources_by_pid.get(pid, {})
            resource_type = str(record.get("resource_type") or "none")
            resource_index = int(record.get("resource_index") or 0)
            resource_amount = int(record.get("resource_amount") or 0)
            f.write(f"{int(pid)};{resource_type};{resource_index};{resource_amount}\n")


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
    happiness_values = _build_happiness_lookup(
        land,
        gdp_rows=gdp_rows,
        ideology_rows=ideology_rows,
    )
    terrain_values = _build_terrain_lookup(
        land,
        population_rows=rows,
    )
    resources_values = _build_resource_lookup(
        land,
        population_rows=rows,
        gdp_rows=gdp_rows,
        terrain_by_pid=terrain_values,
    )

    print("[EXPORT] Resources CSV...")
    write_resources_csv(resources_values, os.path.join(OUT, "Resources.csv"))

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
        happiness_by_pid=happiness_values,
        terrain_by_pid=terrain_values,
        resources_by_pid=resources_values,
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

    print("[EXPORT] Happiness Map...")
    export_happiness_map(
        id_map,
        sea_regions,
        bounds,
        happiness=happiness_values,
        max_pid=max_pid,
    )

    print("[EXPORT] Terrain Map...")
    export_terrain_map(
        id_map,
        sea_regions,
        bounds,
        terrain_by_pid=terrain_values,
        max_pid=max_pid,
    )

    print("[EXPORT] Resources Map...")
    export_resources_map(
        id_map,
        sea_regions,
        bounds,
        resources_by_pid=resources_values,
        max_pid=max_pid,
    )

    export_states(land)
    export_state_files(land)
    _remove_legacy_custom_flag_artifact()

    print("[EXPORT] EXPORT COMPLETE")
