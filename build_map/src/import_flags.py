import argparse
import ast
import csv
import glob
import json
import os
import re
import time
import unicodedata
from typing import Dict, List, Sequence, Tuple
from urllib.parse import unquote, urlencode, urlparse
from urllib.request import Request, urlopen

BASE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUT_DIR = os.path.join(BASE, "opengs_export", "Flags")
DEFAULT_MANIFEST_PATH = os.path.join(BASE, "opengs_export", "country_flags.csv")
DEFAULT_VARIANT_OUT_DIR = os.path.join(BASE, "opengs_export", "FlagsIdeology")
DEFAULT_VARIANT_MANIFEST_PATH = os.path.join(BASE, "opengs_export", "country_flags_ideology.csv")
STATES_PATH = os.path.join(BASE, "opengs_export", "States.txt")
BUILD_MAP_PATH = os.path.join(BASE, "build_map.py")

WDQS_URL = "https://query.wikidata.org/sparql"
DEFAULT_TIMEOUT = 30
USER_AGENT = "map_generator_godot-flag-importer/1.0"

VALID_EXTENSIONS = {".svg", ".png", ".jpg", ".jpeg", ".webp", ".gif"}
# Some codes in Natural Earth differ from ISO-3166-1 alpha-3 used by Wikidata.
REQUEST_ISO_OVERRIDES = {
    "KOS": "XKX",
}
MANUAL_QID_FALLBACK = {
    "KOS": "Q1246",
}

DEFAULT_VARIANT_IDEOLOGIES: Tuple[str, ...] = (
    "demokracie",
    "autokracie",
    "kralovstvi",
    "fasismus",
    "nacismus",
)

# Targeted historical overrides requested by the user.
IDEOLOGY_FLAG_OVERRIDES = {
    (
        "DEU",
        "autokracie",
    ): "https://commons.wikimedia.org/wiki/Special:FilePath/Flag%20of%20Germany%20%281935%E2%80%931945%29.svg",
    (
        "DEU",
        "nacismus",
    ): "https://commons.wikimedia.org/wiki/Special:FilePath/Flag%20of%20Germany%20%281935%E2%80%931945%29.svg",
    (
        "ITA",
        "autokracie",
    ): "https://commons.wikimedia.org/wiki/Special:FilePath/Flag%20of%20Italy%20%281861%E2%80%931946%29.svg",
    (
        "ITA",
        "fasismus",
    ): "https://commons.wikimedia.org/wiki/Special:FilePath/Flag%20of%20Italy%20%281861%E2%80%931946%29.svg",
    (
        "ITA",
        "kralovstvi",
    ): "https://commons.wikimedia.org/wiki/Special:FilePath/Flag%20of%20Italy%20%281861%E2%80%931946%29.svg",
    (
        "CZE",
        "kralovstvi",
    ): "https://commons.wikimedia.org/wiki/Special:FilePath/Flag%20of%20Bohemia.svg",
}


def normalize_iso3(value: str) -> str:
    return str(value or "").strip().upper()


def unique_keep_order(items: Sequence[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def split_cli_iso(raw: str) -> List[str]:
    parts = re.split(r"[\s,;]+", raw or "")
    return [normalize_iso3(p) for p in parts if normalize_iso3(p)]


def normalize_ideology(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    if not text:
        return ""

    alias_map = {
        "demokracie": "demokracie",
        "democracy": "demokracie",
        "democratic": "demokracie",
        "autokracie": "autokracie",
        "autocracy": "autokracie",
        "autocratic": "autokracie",
        "dictatorship": "autokracie",
        "diktatura": "autokracie",
        "kralovstvi": "kralovstvi",
        "kralostvi": "kralovstvi",
        "monarchie": "kralovstvi",
        "monarchy": "kralovstvi",
        "kingdom": "kralovstvi",
        "constitutional monarchy": "kralovstvi",
        "fasismus": "fasismus",
        "fascism": "fasismus",
        "fascist": "fasismus",
        "nacismus": "nacismus",
        "nazismus": "nacismus",
        "nazism": "nacismus",
        "nazi": "nacismus",
    }

    if text in alias_map:
        return alias_map[text]

    for token in text.split():
        if token in alias_map:
            return alias_map[token]

    return text.replace(" ", "_")


def split_cli_ideologies(raw: str) -> List[str]:
    parts = re.split(r"[\s,;]+", raw or "")
    normalized = [normalize_ideology(p) for p in parts]
    cleaned = [item for item in normalized if item]
    return unique_keep_order(cleaned)


def read_iso3_from_states(states_path: str) -> List[str]:
    if not os.path.exists(states_path):
        return []

    result: List[str] = []
    with open(states_path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            iso = normalize_iso3(line.split(";", 1)[0])
            if re.fullmatch(r"[A-Z0-9]{3}", iso):
                result.append(iso)

    return unique_keep_order(result)


def _extract_string_list(node) -> List[str]:
    if not isinstance(node, (ast.List, ast.Tuple)):
        return []

    values: List[str] = []
    for elt in node.elts:
        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
            values.append(normalize_iso3(elt.value))

    return [v for v in values if re.fullmatch(r"[A-Z0-9]{3}", v)]


def read_iso3_from_build_map(path: str) -> List[str]:
    if not os.path.exists(path):
        return []

    with open(path, "r", encoding="utf-8") as handle:
        source = handle.read()

    tree = ast.parse(source, filename=path)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "EUROPE_COUNTRIES":
                    values = _extract_string_list(node.value)
                    return unique_keep_order(values)

        if isinstance(node, ast.AnnAssign):
            target = node.target
            if isinstance(target, ast.Name) and target.id == "EUROPE_COUNTRIES":
                values = _extract_string_list(node.value)
                return unique_keep_order(values)

    return []


def build_iso_flag_query(iso_codes: Sequence[str]) -> str:
    values = " ".join(f'"{code}"' for code in iso_codes)
    return (
        "SELECT ?iso3 ?flag WHERE {\n"
        f"  VALUES ?iso3 {{ {values} }}\n"
        "  ?country wdt:P298 ?iso3;\n"
        "           wdt:P41 ?flag.\n"
        "}"
    )


def build_qid_flag_query(qid: str) -> str:
    return (
        "SELECT ?flag WHERE {\n"
        f"  wd:{qid} wdt:P41 ?flag.\n"
        "}\n"
        "LIMIT 1"
    )


def fetch_wdqs_json(query: str, timeout: int, retries: int = 3) -> Dict:
    params = urlencode({"query": query, "format": "json"})
    url = f"{WDQS_URL}?{params}"

    last_error = None
    for attempt in range(retries):
        try:
            request = Request(
                url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "application/sparql-results+json",
                },
            )
            with urlopen(request, timeout=timeout) as response:
                payload = response.read().decode("utf-8")
            return json.loads(payload)
        except Exception as exc:
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(1.0 + attempt)

    raise RuntimeError(f"WDQS request failed after retries: {last_error}")


def query_iso_flag_urls(iso_codes: Sequence[str], timeout: int) -> Dict[str, str]:
    if not iso_codes:
        return {}

    payload = fetch_wdqs_json(build_iso_flag_query(iso_codes), timeout=timeout)
    results = payload.get("results", {}).get("bindings", [])

    out: Dict[str, str] = {}
    for row in results:
        iso = normalize_iso3(row.get("iso3", {}).get("value", ""))
        url = str(row.get("flag", {}).get("value", "")).strip()
        if iso and url and iso not in out:
            out[iso] = url

    return out


def query_flag_url_for_qid(qid: str, timeout: int) -> str:
    payload = fetch_wdqs_json(build_qid_flag_query(qid), timeout=timeout)
    results = payload.get("results", {}).get("bindings", [])
    if not results:
        return ""

    return str(results[0].get("flag", {}).get("value", "")).strip()


def infer_extension(url: str, content_type: str) -> str:
    path = unquote(urlparse(url).path)
    ext = os.path.splitext(path)[1].lower()
    if ext in VALID_EXTENSIONS:
        return ext

    ctype = (content_type or "").split(";", 1)[0].strip().lower()
    if ctype == "image/svg+xml":
        return ".svg"
    if ctype == "image/png":
        return ".png"
    if ctype in {"image/jpeg", "image/jpg"}:
        return ".jpg"
    if ctype == "image/webp":
        return ".webp"
    if ctype == "image/gif":
        return ".gif"

    return ".svg"


def existing_flag_files(stem_path: str) -> List[str]:
    candidates = glob.glob(stem_path + ".*")
    files = []
    for candidate in candidates:
        _, ext = os.path.splitext(candidate)
        if ext.lower() in VALID_EXTENSIONS:
            files.append(candidate)
    return sorted(files)


def download_flag(url: str, stem_path: str, timeout: int, retries: int = 3) -> Dict[str, str]:
    last_error = None
    for attempt in range(retries):
        try:
            request = Request(
                url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "image/*,*/*;q=0.8",
                },
            )
            with urlopen(request, timeout=timeout) as response:
                data = response.read()
                final_url = response.geturl()
                content_type = response.headers.get("Content-Type", "")

            ext = infer_extension(final_url, content_type)
            out_path = stem_path + ext
            tmp_path = out_path + ".tmp"

            with open(tmp_path, "wb") as handle:
                handle.write(data)
            os.replace(tmp_path, out_path)

            return {
                "path": out_path,
                "source_url": final_url,
            }
        except Exception as exc:
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(1.0 + attempt)

    raise RuntimeError(f"Download failed after retries: {last_error}")


def ensure_parent_dir(path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def resolve_target_iso3(cli_iso: str) -> List[str]:
    if cli_iso:
        selected = split_cli_iso(cli_iso)
        selected = [code for code in selected if re.fullmatch(r"[A-Z0-9]{3}", code)]
        return unique_keep_order(selected)

    from_states = read_iso3_from_states(STATES_PATH)
    if from_states:
        print(f"[FLAGS] Loaded {len(from_states)} country codes from States.txt")
        return from_states

    from_build_map = read_iso3_from_build_map(BUILD_MAP_PATH)
    if from_build_map:
        print(f"[FLAGS] Loaded {len(from_build_map)} country codes from build_map.py")
        return from_build_map

    return []


def write_manifest(path: str, rows: Sequence[Dict[str, str]]) -> None:
    ensure_parent_dir(path)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(["country_iso3", "flag_file", "source_url", "status", "note"])
        for row in rows:
            writer.writerow(
                [
                    row.get("country_iso3", ""),
                    row.get("flag_file", ""),
                    row.get("source_url", ""),
                    row.get("status", ""),
                    row.get("note", ""),
                ]
            )


def write_variant_manifest(path: str, rows: Sequence[Dict[str, str]]) -> None:
    ensure_parent_dir(path)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(["country_iso3", "ideology", "flag_file", "source_url", "status", "note"])
        for row in rows:
            writer.writerow(
                [
                    row.get("country_iso3", ""),
                    row.get("ideology", ""),
                    row.get("flag_file", ""),
                    row.get("source_url", ""),
                    row.get("status", ""),
                    row.get("note", ""),
                ]
            )


def join_notes(*parts: str) -> str:
    values = [str(p).strip() for p in parts if str(p).strip()]
    return "|".join(values)


def resolve_flag_sources(iso_codes: Sequence[str], timeout: int) -> Dict[str, Dict[str, str]]:
    query_codes = unique_keep_order([REQUEST_ISO_OVERRIDES.get(code, code) for code in iso_codes])
    iso_to_url = query_iso_flag_urls(query_codes, timeout=timeout)

    out: Dict[str, Dict[str, str]] = {}
    for iso in iso_codes:
        source_key = REQUEST_ISO_OVERRIDES.get(iso, iso)
        source_url = iso_to_url.get(source_key, "")
        note = ""

        if source_url and source_key != iso:
            note = f"iso_alias:{iso}->{source_key}"
        elif not source_url and iso in MANUAL_QID_FALLBACK:
            source_url = query_flag_url_for_qid(MANUAL_QID_FALLBACK[iso], timeout=timeout)
            if source_url:
                note = f"fallback_qid:{MANUAL_QID_FALLBACK[iso]}"

        out[iso] = {
            "source_url": source_url,
            "note": note,
        }

    return out


def choose_ideology_source_url(iso: str, ideology: str, base_source: Dict[str, str]) -> Tuple[str, str]:
    override_url = IDEOLOGY_FLAG_OVERRIDES.get((iso, ideology), "")
    if override_url:
        return override_url, "historical_override"

    base_url = str(base_source.get("source_url", "") or "").strip()
    base_note = str(base_source.get("note", "") or "").strip()
    if base_url:
        return base_url, join_notes("fallback_base_flag", base_note)

    return "", ""


def run_import(iso_codes: Sequence[str], out_dir: str, manifest_path: str, force: bool, timeout: int) -> int:
    os.makedirs(out_dir, exist_ok=True)

    source_by_iso = resolve_flag_sources(iso_codes, timeout=timeout)

    manifest_rows: List[Dict[str, str]] = []
    downloaded = 0
    reused = 0
    missing = 0

    for index, iso in enumerate(iso_codes, start=1):
        stem = os.path.join(out_dir, iso)
        source_entry = source_by_iso.get(iso, {})
        known_source_url = str(source_entry.get("source_url", "") or "").strip()
        known_source_note = str(source_entry.get("note", "") or "").strip()

        existing = existing_flag_files(stem)
        if existing and not force:
            reused += 1
            manifest_rows.append(
                {
                    "country_iso3": iso,
                    "flag_file": os.path.basename(existing[0]),
                    "source_url": known_source_url,
                    "status": "existing",
                    "note": join_notes(known_source_note, "kept_existing_file"),
                }
            )
            continue

        source_url = known_source_url
        note = known_source_note

        if not source_url:
            missing += 1
            manifest_rows.append(
                {
                    "country_iso3": iso,
                    "flag_file": "",
                    "source_url": "",
                    "status": "missing",
                    "note": "no_flag_url_found",
                }
            )
            print(f"[FLAGS] {index}/{len(iso_codes)} {iso}: missing URL")
            continue

        try:
            download_result = download_flag(source_url, stem, timeout=timeout)
            out_path = download_result["path"]
            final_url = download_result["source_url"]

            # Keep only the latest extension for one ISO3 to avoid duplicates.
            for old_path in existing_flag_files(stem):
                if old_path != out_path:
                    try:
                        os.remove(old_path)
                    except OSError:
                        pass

            downloaded += 1
            manifest_rows.append(
                {
                    "country_iso3": iso,
                    "flag_file": os.path.basename(out_path),
                    "source_url": final_url,
                    "status": "downloaded",
                    "note": note,
                }
            )
            print(f"[FLAGS] {index}/{len(iso_codes)} {iso}: {os.path.basename(out_path)}")
        except Exception as exc:
            missing += 1
            manifest_rows.append(
                {
                    "country_iso3": iso,
                    "flag_file": "",
                    "source_url": source_url,
                    "status": "error",
                    "note": str(exc),
                }
            )
            print(f"[FLAGS] {index}/{len(iso_codes)} {iso}: ERROR {exc}")

        # Small delay avoids hammering external hosts.
        time.sleep(0.1)

    write_manifest(manifest_path, manifest_rows)

    print("[FLAGS] -----------------------------")
    print(f"[FLAGS] Total ISO3 codes: {len(iso_codes)}")
    print(f"[FLAGS] Downloaded: {downloaded}")
    print(f"[FLAGS] Reused existing: {reused}")
    print(f"[FLAGS] Missing/error: {missing}")
    print(f"[FLAGS] Manifest: {manifest_path}")

    return 0 if missing == 0 else 2


def run_import_ideology_variants(
    iso_codes: Sequence[str],
    ideologies: Sequence[str],
    out_dir: str,
    manifest_path: str,
    force: bool,
    timeout: int,
) -> int:
    os.makedirs(out_dir, exist_ok=True)

    source_by_iso = resolve_flag_sources(iso_codes, timeout=timeout)

    manifest_rows: List[Dict[str, str]] = []
    downloaded = 0
    reused = 0
    missing = 0
    total = len(iso_codes) * len(ideologies)
    step = 0

    for iso in iso_codes:
        base_source = source_by_iso.get(iso, {})
        for ideology in ideologies:
            step += 1
            stem = os.path.join(out_dir, f"{iso}__{ideology}")
            existing = existing_flag_files(stem)

            source_url, source_note = choose_ideology_source_url(iso, ideology, base_source)

            if existing and not force:
                reused += 1
                manifest_rows.append(
                    {
                        "country_iso3": iso,
                        "ideology": ideology,
                        "flag_file": os.path.basename(existing[0]),
                        "source_url": source_url,
                        "status": "existing",
                        "note": join_notes(source_note, "kept_existing_file"),
                    }
                )
                continue

            if not source_url:
                missing += 1
                manifest_rows.append(
                    {
                        "country_iso3": iso,
                        "ideology": ideology,
                        "flag_file": "",
                        "source_url": "",
                        "status": "missing",
                        "note": "no_flag_url_found",
                    }
                )
                print(f"[FLAGS] {step}/{total} {iso} {ideology}: missing URL")
                continue

            try:
                download_result = download_flag(source_url, stem, timeout=timeout)
                out_path = download_result["path"]
                final_url = download_result["source_url"]

                # Keep only the latest extension for one ISO3+ideology to avoid duplicates.
                for old_path in existing_flag_files(stem):
                    if old_path != out_path:
                        try:
                            os.remove(old_path)
                        except OSError:
                            pass

                downloaded += 1
                manifest_rows.append(
                    {
                        "country_iso3": iso,
                        "ideology": ideology,
                        "flag_file": os.path.basename(out_path),
                        "source_url": final_url,
                        "status": "downloaded",
                        "note": source_note,
                    }
                )
                print(f"[FLAGS] {step}/{total} {iso} {ideology}: {os.path.basename(out_path)}")
            except Exception as exc:
                missing += 1
                manifest_rows.append(
                    {
                        "country_iso3": iso,
                        "ideology": ideology,
                        "flag_file": "",
                        "source_url": source_url,
                        "status": "error",
                        "note": str(exc),
                    }
                )
                print(f"[FLAGS] {step}/{total} {iso} {ideology}: ERROR {exc}")

            # Small delay avoids hammering external hosts.
            time.sleep(0.1)

    write_variant_manifest(manifest_path, manifest_rows)

    print("[FLAGS] -----------------------------")
    print(f"[FLAGS] Total combinations: {total}")
    print(f"[FLAGS] Downloaded: {downloaded}")
    print(f"[FLAGS] Reused existing: {reused}")
    print(f"[FLAGS] Missing/error: {missing}")
    print(f"[FLAGS] Manifest: {manifest_path}")

    return 0 if missing == 0 else 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Download country flags to opengs_export/Flags using ISO3 country codes "
            "compatible with build_map (e.g. CZE, DEU). Optionally generate ideology "
            "variants (ISO3__ideology.ext)."
        )
    )
    parser.add_argument(
        "--iso",
        default="",
        help="Optional ISO3 list (comma/space/semicolon separated). If omitted, States.txt is used first.",
    )
    parser.add_argument(
        "--out-dir",
        default=DEFAULT_OUT_DIR,
        help=f"Output directory for flag files (default: {DEFAULT_OUT_DIR})",
    )
    parser.add_argument(
        "--manifest",
        default=DEFAULT_MANIFEST_PATH,
        help=f"Manifest CSV path (default: {DEFAULT_MANIFEST_PATH})",
    )
    parser.add_argument(
        "--ideology-variants",
        action="store_true",
        help="Generate ideology-specific variants instead of one base flag per ISO3.",
    )
    parser.add_argument(
        "--ideologies",
        default=",".join(DEFAULT_VARIANT_IDEOLOGIES),
        help=(
            "Ideology list for --ideology-variants (comma/space/semicolon separated). "
            f"Default: {','.join(DEFAULT_VARIANT_IDEOLOGIES)}"
        ),
    )
    parser.add_argument(
        "--variant-out-dir",
        default=DEFAULT_VARIANT_OUT_DIR,
        help=f"Output directory for ideology variants (default: {DEFAULT_VARIANT_OUT_DIR})",
    )
    parser.add_argument(
        "--variant-manifest",
        default=DEFAULT_VARIANT_MANIFEST_PATH,
        help=f"Variant manifest CSV path (default: {DEFAULT_VARIANT_MANIFEST_PATH})",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT,
        help=f"HTTP timeout in seconds (default: {DEFAULT_TIMEOUT})",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download even when an ISO3 flag file already exists.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    iso_codes = resolve_target_iso3(args.iso)
    if not iso_codes:
        print("[FLAGS] No ISO3 country codes found. Use --iso or generate States.txt first.")
        return 1

    timeout = max(int(args.timeout), 1)

    if bool(args.ideology_variants):
        ideologies = split_cli_ideologies(args.ideologies)
        if not ideologies:
            ideologies = list(DEFAULT_VARIANT_IDEOLOGIES)

        print(f"[FLAGS] Target ISO3 count: {len(iso_codes)}")
        print(f"[FLAGS] Ideology variants: {', '.join(ideologies)}")
        print(f"[FLAGS] Variant output directory: {args.variant_out_dir}")

        return run_import_ideology_variants(
            iso_codes=iso_codes,
            ideologies=ideologies,
            out_dir=args.variant_out_dir,
            manifest_path=args.variant_manifest,
            force=bool(args.force),
            timeout=timeout,
        )

    print(f"[FLAGS] Target ISO3 count: {len(iso_codes)}")
    print(f"[FLAGS] Output directory: {args.out_dir}")

    return run_import(
        iso_codes=iso_codes,
        out_dir=args.out_dir,
        manifest_path=args.manifest,
        force=bool(args.force),
        timeout=timeout,
    )


if __name__ == "__main__":
    raise SystemExit(main())
