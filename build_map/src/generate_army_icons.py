import argparse
import csv
import hashlib
import os
from typing import Dict, List, Sequence

import import_flags

BASE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUT_DIR = os.path.join(BASE, "opengs_export", "ArmyIcons")
DEFAULT_MANIFEST_PATH = os.path.join(BASE, "opengs_export", "country_army_icons.csv")
DEFAULT_TEMPLATE_PATH = os.path.join(BASE, "opengs_export", "ArmyIcons", "ArmyIconTemplate.svg")
DEFAULT_IDEOLOGY_TEMPLATE_DIR = os.path.join(BASE, "opengs_export", "ArmyIconsIdeologyTemplates")

# User-defined thematic base colors per country/state tag.
THEME_BASE_COLORS: Dict[str, str] = {
    "ALB": "#D13A3A",
    "AND": "#1A409A",
    "AUT": "#FFFFFF",
    "BLR": "#8CA35E",
    "BEL": "#D4B04C",
    "BIH": "#456285",
    "BGR": "#426145",
    "HRV": "#5C7691",
    "CYP": "#E3A336",
    "CZE": "#D49035",
    "DNK": "#9E333D",
    "EST": "#266E73",
    "FIN": "#96B6D1",
    "FRA": "#2944A6",
    "DEU": "#666666",
    "GRC": "#5CA1D6",
    "HUN": "#A35A47",
    "ISL": "#88ADC9",
    "IRL": "#388F4F",
    "ITA": "#408F45",
    "KOS": "#454B87",
    "GEO": "#D48035",
    "LVA": "#85616D",
    "LIE": "#314C7D",
    "LTU": "#A6A34E",
    "LUX": "#8FA9D4",
    "MLT": "#D95959",
    "MDA": "#D4A94C",
    "MCO": "#D63636",
    "MNE": "#3D7873",
    "NLD": "#D97529",
    "MKD": "#D14532",
    "NOR": "#6E88A1",
    "POL": "#C44D64",
    "PRT": "#2A7A38",
    "ROU": "#C9A936",
    "RUS": "#316E40",
    "SMR": "#7BA1C7",
    "SRB": "#B8939D",
    "SVK": "#3A5B8C",
    "SVN": "#4E8272",
    "ESP": "#D4BC2C",
    "SWE": "#286C9E",
    "CHE": "#AD2A2A",
    "TUR": "#3A8C67",
    "UKR": "#DEC243",
    "GBR": "#9E2633",
    "SEA": "#5b556f",
}


def unique_keep_order(items: Sequence[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def parse_iso_list(raw: str) -> List[str]:
    if not raw:
        return []
    parts = import_flags.split_cli_iso(raw)
    out: List[str] = []
    for code in parts:
        code = import_flags.normalize_iso3(code)
        if len(code) == 3 and code.isalnum():
            out.append(code)
    return unique_keep_order(out)


def resolve_target_iso3(cli_iso: str) -> List[str]:
    selected = parse_iso_list(cli_iso)
    if selected:
        return selected
    return import_flags.resolve_target_iso3("")


def to_hex(r: int, g: int, b: int) -> str:
    return f"#{r:02x}{g:02x}{b:02x}"


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    text = str(value or "").strip()
    if text.startswith("#"):
        text = text[1:]
    if len(text) != 6:
        raise ValueError(f"Invalid hex color: {value}")
    return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)


def mix_channel(channel: int, target: int, amount: float) -> int:
    value = int(round(channel + (target - channel) * amount))
    return max(0, min(255, value))


def blend_hex(hex_color: str, target_rgb: tuple[int, int, int], amount: float) -> str:
    r, g, b = hex_to_rgb(hex_color)
    tr, tg, tb = target_rgb
    return to_hex(
        mix_channel(r, tr, amount),
        mix_channel(g, tg, amount),
        mix_channel(b, tb, amount),
    )


def iso_palette(iso: str) -> Dict[str, str]:
    themed = THEME_BASE_COLORS.get(iso)
    if themed:
        # Keep country identity color as base and derive icon layers from it.
        return {
            "base": themed,
            "accent": blend_hex(themed, (255, 255, 255), 0.35),
            "edge": blend_hex(themed, (0, 0, 0), 0.30),
        }

    digest = hashlib.sha1(iso.encode("ascii", "ignore")).digest()

    # Keep colors in a readable, game-UI-safe range.
    base_r = 40 + (digest[0] % 120)
    base_g = 40 + (digest[1] % 120)
    base_b = 40 + (digest[2] % 120)

    accent_r = 140 + (digest[3] % 100)
    accent_g = 140 + (digest[4] % 100)
    accent_b = 140 + (digest[5] % 100)

    edge_r = max(10, base_r - 20)
    edge_g = max(10, base_g - 20)
    edge_b = max(10, base_b - 20)

    return {
        "base": to_hex(base_r, base_g, base_b),
        "accent": to_hex(accent_r, accent_g, accent_b),
        "edge": to_hex(edge_r, edge_g, edge_b),
    }


def build_icon_svg(iso: str) -> str:
    colors = iso_palette(iso)
    return f"""<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"96\" height=\"96\" viewBox=\"0 0 96 96\">\n  <defs>\n    <linearGradient id=\"bg\" x1=\"0%\" y1=\"0%\" x2=\"100%\" y2=\"100%\">\n      <stop offset=\"0%\" stop-color=\"{colors['base']}\"/>\n      <stop offset=\"100%\" stop-color=\"{colors['edge']}\"/>\n    </linearGradient>\n  </defs>\n  <rect x=\"1\" y=\"1\" width=\"94\" height=\"94\" rx=\"14\" fill=\"url(#bg)\" stroke=\"#111111\" stroke-width=\"2\"/>\n  <path d=\"M48 16 L68 24 L64 56 L48 74 L32 56 L28 24 Z\" fill=\"{colors['accent']}\" stroke=\"#111111\" stroke-width=\"2\"/>\n  <path d=\"M27 66 L46 47 L50 51 L31 70 Z\" fill=\"#e8e8e8\" stroke=\"#111111\" stroke-width=\"1.2\"/>\n  <path d=\"M69 66 L50 47 L46 51 L65 70 Z\" fill=\"#e8e8e8\" stroke=\"#111111\" stroke-width=\"1.2\"/>\n  <rect x=\"26\" y=\"67\" width=\"7\" height=\"5\" fill=\"#5a3d2b\" stroke=\"#111111\" stroke-width=\"1\"/>\n  <rect x=\"63\" y=\"67\" width=\"7\" height=\"5\" fill=\"#5a3d2b\" stroke=\"#111111\" stroke-width=\"1\"/>\n  <text x=\"48\" y=\"45\" font-size=\"15\" font-weight=\"700\" text-anchor=\"middle\" fill=\"#111111\" font-family=\"Verdana, Tahoma, sans-serif\">{iso}</text>\n</svg>\n"""


def build_template_svg() -> str:
        # White fill keeps icon easy to tint in Godot via modulate/self_modulate.
        return """<svg xmlns="http://www.w3.org/2000/svg" width="96" height="96" viewBox="0 0 96 96">
    <rect x="1" y="1" width="94" height="94" rx="14" fill="#ffffff" fill-opacity="0.28" stroke="#ffffff" stroke-width="2"/>
    <path d="M48 16 L68 24 L64 56 L48 74 L32 56 L28 24 Z" fill="#ffffff" fill-opacity="0.90" stroke="#ffffff" stroke-width="2"/>
    <path d="M27 66 L46 47 L50 51 L31 70 Z" fill="#ffffff" fill-opacity="0.95"/>
    <path d="M69 66 L50 47 L46 51 L65 70 Z" fill="#ffffff" fill-opacity="0.95"/>
    <rect x="26" y="67" width="7" height="5" fill="#ffffff" fill-opacity="0.80"/>
    <rect x="63" y="67" width="7" height="5" fill="#ffffff" fill-opacity="0.80"/>
</svg>
"""


def build_ideology_symbol_svg(ideology: str) -> str:
    symbols = {
        "demokracie": '<circle cx="48" cy="44" r="9" fill="#ffffff" fill-opacity="0.96"/><path d="M48 34 L51 43 L61 43 L53 49 L56 58 L48 52 L40 58 L43 49 L35 43 L45 43 Z" fill="#ffffff" fill-opacity="0.75"/>',
        "autokracie": '<path d="M35 46 L40 38 L48 44 L56 38 L61 46 L57 54 L39 54 Z" fill="#ffffff" fill-opacity="0.95"/><rect x="42" y="54" width="12" height="4" fill="#ffffff" fill-opacity="0.85"/>',
        "kralovstvi": '<path d="M34 45 L38 36 L46 42 L50 35 L58 42 L62 36 L66 45 L60 55 L36 55 Z" fill="#ffffff" fill-opacity="0.95"/><rect x="40" y="55" width="16" height="4" fill="#ffffff" fill-opacity="0.85"/>',
        "fasismus": '<path d="M40 34 L56 34 L48 46 L60 46 L40 64 L46 50 L36 50 Z" fill="#ffffff" fill-opacity="0.94"/>',
        "nacismus": '<rect x="41" y="37" width="14" height="14" fill="#ffffff" fill-opacity="0.95"/><rect x="36" y="52" width="24" height="4" fill="#ffffff" fill-opacity="0.85"/>',
        "komunismus": '<path d="M39 54 L42 49 L47 50 L50 54 L45 58 Z" fill="#ffffff" fill-opacity="0.95"/><path d="M56 36 L52 46 L58 46 L49 60 L52 50 L46 50 Z" fill="#ffffff" fill-opacity="0.88"/>',
    }
    return symbols.get(ideology, '<circle cx="48" cy="47" r="8" fill="#ffffff" fill-opacity="0.9"/>')


def build_ideology_template_svg(ideology: str) -> str:
    symbol = build_ideology_symbol_svg(ideology)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="96" height="96" viewBox="0 0 96 96">
  <rect x="1" y="1" width="94" height="94" rx="14" fill="#ffffff" fill-opacity="0.24" stroke="#ffffff" stroke-width="2"/>
  <path d="M48 16 L68 24 L64 56 L48 74 L32 56 L28 24 Z" fill="#ffffff" fill-opacity="0.88" stroke="#ffffff" stroke-width="2"/>
  <path d="M27 66 L46 47 L50 51 L31 70 Z" fill="#ffffff" fill-opacity="0.93"/>
  <path d="M69 66 L50 47 L46 51 L65 70 Z" fill="#ffffff" fill-opacity="0.93"/>
  <rect x="26" y="67" width="7" height="5" fill="#ffffff" fill-opacity="0.78"/>
  <rect x="63" y="67" width="7" height="5" fill="#ffffff" fill-opacity="0.78"/>
  {symbol}
</svg>
"""


def clamp_value_0_100(value: int) -> int:
    return max(0, min(100, int(value)))


def parse_cli_values(raw: str) -> List[int]:
    if not raw:
        return [20, 50, 80]
    out: List[int] = []
    for part in raw.replace(";", ",").replace(" ", ",").split(","):
        text = part.strip()
        if not text:
            continue
        try:
            out.append(clamp_value_0_100(int(text)))
        except ValueError:
            continue
    if not out:
        return [20, 50, 80]
    return sorted(unique_keep_order(out))


def build_ideology_template_svg_with_value(ideology: str, value: int) -> str:
    v = clamp_value_0_100(value)
    symbol = build_ideology_symbol_svg(ideology)
    # 0..100 -> 0.18..0.86 for center glow/fill intensity.
    strength = 0.18 + (v / 100.0) * 0.68
    ring = 12 + int((v / 100.0) * 22)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="96" height="96" viewBox="0 0 96 96">
  <rect x="1" y="1" width="94" height="94" rx="14" fill="#ffffff" fill-opacity="0.22" stroke="#ffffff" stroke-width="2"/>
  <path d="M48 16 L68 24 L64 56 L48 74 L32 56 L28 24 Z" fill="#ffffff" fill-opacity="0.62" stroke="#ffffff" stroke-width="2"/>
  <path d="M27 66 L46 47 L50 51 L31 70 Z" fill="#ffffff" fill-opacity="0.90"/>
  <path d="M69 66 L50 47 L46 51 L65 70 Z" fill="#ffffff" fill-opacity="0.90"/>
  <rect x="26" y="67" width="7" height="5" fill="#ffffff" fill-opacity="0.76"/>
  <rect x="63" y="67" width="7" height="5" fill="#ffffff" fill-opacity="0.76"/>
  <circle cx="48" cy="47" r="{ring}" fill="#ffffff" fill-opacity="{strength:.3f}"/>
  {symbol}
</svg>
"""


def ensure_parent_dir(path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def write_text_atomic(path: str, content: str) -> None:
    ensure_parent_dir(path)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8", newline="") as handle:
        handle.write(content)
    os.replace(tmp_path, path)


def write_manifest(path: str, rows: Sequence[Dict[str, str]]) -> None:
    ensure_parent_dir(path)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(["country_iso3", "icon_file", "status", "note"])
        for row in rows:
            writer.writerow(
                [
                    row.get("country_iso3", ""),
                    row.get("icon_file", ""),
                    row.get("status", ""),
                    row.get("note", ""),
                ]
            )


def write_template(path: str, force: bool) -> None:
    if os.path.exists(path) and not force:
        print(f"[ARMY] Template exists: {path}")
        return
    write_text_atomic(path, build_template_svg())
    print(f"[ARMY] Template written: {path}")


def split_cli_ideologies(raw: str) -> List[str]:
    if not raw:
        return list(import_flags.DEFAULT_VARIANT_IDEOLOGIES)
    out: List[str] = []
    for item in raw.replace(";", ",").replace(" ", ",").split(","):
        normalized = import_flags.normalize_ideology(item)
        if normalized:
            out.append(normalized)
    return unique_keep_order(out)


def write_ideology_templates(out_dir: str, ideologies: Sequence[str], force: bool) -> None:
    os.makedirs(out_dir, exist_ok=True)
    for ideology in ideologies:
        path = os.path.join(out_dir, f"ArmyIconTemplate__{ideology}.svg")
        if os.path.exists(path) and not force:
            print(f"[ARMY] Ideology template exists: {path}")
            continue
        write_text_atomic(path, build_ideology_template_svg(ideology))
        print(f"[ARMY] Ideology template written: {path}")


def write_ideology_value_templates(out_dir: str, ideologies: Sequence[str], values: Sequence[int], force: bool) -> None:
    os.makedirs(out_dir, exist_ok=True)
    for ideology in ideologies:
        for value in values:
            clamped = clamp_value_0_100(value)
            path = os.path.join(out_dir, f"ArmyIconTemplate__{ideology}__v{clamped:03d}.svg")
            if os.path.exists(path) and not force:
                print(f"[ARMY] Ideology-value template exists: {path}")
                continue
            write_text_atomic(path, build_ideology_template_svg_with_value(ideology, clamped))
            print(f"[ARMY] Ideology-value template written: {path}")


def run_generation(iso_codes: Sequence[str], out_dir: str, manifest_path: str, force: bool) -> int:
    os.makedirs(out_dir, exist_ok=True)

    rows: List[Dict[str, str]] = []
    generated = 0
    reused = 0

    for idx, iso in enumerate(iso_codes, start=1):
        out_path = os.path.join(out_dir, f"{iso}.svg")

        if os.path.exists(out_path) and not force:
            reused += 1
            rows.append(
                {
                    "country_iso3": iso,
                    "icon_file": os.path.basename(out_path),
                    "status": "existing",
                    "note": "kept_existing_file",
                }
            )
            print(f"[ARMY] {idx}/{len(iso_codes)} {iso}: existing")
            continue

        svg = build_icon_svg(iso)
        write_text_atomic(out_path, svg)

        generated += 1
        rows.append(
            {
                "country_iso3": iso,
                "icon_file": os.path.basename(out_path),
                "status": "generated",
                "note": "generated_army_icon_svg",
            }
        )
        print(f"[ARMY] {idx}/{len(iso_codes)} {iso}: {os.path.basename(out_path)}")

    write_manifest(manifest_path, rows)

    print("[ARMY] -----------------------------")
    print(f"[ARMY] Total ISO3 codes: {len(iso_codes)}")
    print(f"[ARMY] Generated: {generated}")
    print(f"[ARMY] Reused existing: {reused}")
    print(f"[ARMY] Manifest: {manifest_path}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate one army icon per country ISO3 code used by the map export."
    )
    parser.add_argument(
        "--iso",
        default="",
        help="Optional ISO3 list (comma/space/semicolon separated). If omitted, States.txt/build_map.py is used.",
    )
    parser.add_argument(
        "--out-dir",
        default=DEFAULT_OUT_DIR,
        help=f"Output directory for generated army icons (default: {DEFAULT_OUT_DIR})",
    )
    parser.add_argument(
        "--manifest",
        default=DEFAULT_MANIFEST_PATH,
        help=f"Manifest CSV path (default: {DEFAULT_MANIFEST_PATH})",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate icons even when target files already exist.",
    )
    parser.add_argument(
        "--template-out",
        default=DEFAULT_TEMPLATE_PATH,
        help=f"Output path for Godot colorable template icon (default: {DEFAULT_TEMPLATE_PATH})",
    )
    parser.add_argument(
        "--template-only",
        action="store_true",
        help="Only write the template icon and skip per-country icon generation.",
    )
    parser.add_argument(
        "--ideology-templates",
        action="store_true",
        help="Generate ideology-specific template icons.",
    )
    parser.add_argument(
        "--ideology-template-dir",
        default=DEFAULT_IDEOLOGY_TEMPLATE_DIR,
        help=f"Output directory for ideology templates (default: {DEFAULT_IDEOLOGY_TEMPLATE_DIR})",
    )
    parser.add_argument(
        "--ideologies",
        default=",".join(import_flags.DEFAULT_VARIANT_IDEOLOGIES),
        help="Ideology list for ideology templates (comma/space/semicolon separated).",
    )
    parser.add_argument(
        "--ideology-value-templates",
        action="store_true",
        help="Generate ideology templates that also encode value strength (0-100).",
    )
    parser.add_argument(
        "--ideology-values",
        default="20,50,80",
        help="Value list for --ideology-value-templates (0-100, comma/space/semicolon separated).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    write_template(path=args.template_out, force=bool(args.force))
    if bool(args.ideology_templates):
        ideology_list = split_cli_ideologies(args.ideologies)
        write_ideology_templates(
            out_dir=args.ideology_template_dir,
            ideologies=ideology_list,
            force=bool(args.force),
        )
        if bool(args.ideology_value_templates):
            write_ideology_value_templates(
                out_dir=args.ideology_template_dir,
                ideologies=ideology_list,
                values=parse_cli_values(args.ideology_values),
                force=bool(args.force),
            )

    if bool(args.template_only):
        return 0

    iso_codes = resolve_target_iso3(args.iso)
    if not iso_codes:
        print("[ARMY] No ISO3 country codes found. Use --iso or generate States.txt first.")
        return 1

    print(f"[ARMY] Target ISO3 count: {len(iso_codes)}")
    print(f"[ARMY] Output directory: {args.out_dir}")
    return run_generation(
        iso_codes=iso_codes,
        out_dir=args.out_dir,
        manifest_path=args.manifest,
        force=bool(args.force),
    )


if __name__ == "__main__":
    raise SystemExit(main())
