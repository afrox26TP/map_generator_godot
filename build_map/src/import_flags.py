# AI-GENERATED
import argparse
import ast
import csv
import glob
import json
import os
import re
import shutil
import time
import unicodedata
from html import escape
from typing import Dict, List, Sequence, Set, Tuple
from urllib.parse import quote, unquote, urlencode, urlparse
from urllib.error import HTTPError
from urllib.request import Request, urlopen

try:
    from PIL import Image
except Exception:
    Image = None

BASE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUT_DIR = os.path.join(BASE, "opengs_export", "Flags")
DEFAULT_MANIFEST_PATH = os.path.join(BASE, "opengs_export", "country_flags.csv")
DEFAULT_VARIANT_OUT_DIR = os.path.join(BASE, "opengs_export", "FlagsIdeology")
DEFAULT_VARIANT_MANIFEST_PATH = os.path.join(BASE, "opengs_export", "country_flags_ideology.csv")
STATES_PATH = os.path.join(BASE, "opengs_export", "States.txt")
BUILD_MAP_PATH = os.path.join(BASE, "build_map.py")
LOCAL_FLAG_HISTORY_PATH = os.path.join(BASE, "flags.csv")
LOCAL_FLAG_CURRENT_PATH = os.path.join(BASE, "flags2.csv")
LOCAL_FLAG_SOURCE_DIRS = (
    os.path.join(BASE, "HOI4 Flags"),
    os.path.join(BASE, "VIC2 Flags"),
)

WDQS_URL = "https://query.wikidata.org/sparql"
COMMONS_API_URL = "https://commons.wikimedia.org/w/api.php"
COMMONS_HISTORICAL_EUROPE_PAGE = "Historical_flags_of_Europe"
DEFAULT_TIMEOUT = 30
USER_AGENT = "map_generator_godot-flag-importer/1.0"

VALID_EXTENSIONS = {".svg", ".png", ".jpg", ".jpeg", ".webp", ".gif"}
LOCAL_MIN_RASTER_WIDTH = 320
LOCAL_MIN_RASTER_HEIGHT = 200
LOWRES_LOCAL_CACHE: Dict[str, bool] = {}

# ISO3 -> known game tag aliases used in bundled HOI4/VIC2 folders.
ISO3_GAME_TAG_ALIASES: Dict[str, Tuple[str, ...]] = {
    "AUT": ("AUS",),
    "DEU": ("GER",),
    "DNK": ("DEN",),
    "ESP": ("SPA",),
    "GBR": ("ENG",),
    "GRC": ("GRE",),
    "HRV": ("CRO",),
    "IRL": ("IRE",),
    "ISL": ("ICE", "ICL"),
    "LTU": ("LIT",),
    "LVA": ("LAT",),
    "MNE": ("MNT",),
    "NLD": ("HOL",),
    "PRT": ("POR",),
    "ROU": ("ROM",),
    "SRB": ("SER",),
    "SVN": ("SLV",),
}

IDEOLOGY_GAME_SUFFIXES: Dict[str, Tuple[str, ...]] = {
    "demokracie": ("democratic", "democracy", "republic"),
    "autokracie": ("neutrality", "monarchy"),
    "kralovstvi": ("neutrality", "monarchy"),
    "fasismus": ("fascism", "fascist"),
    "nacismus": ("fascism", "fascist"),
    "komunismus": ("communism", "communist"),
}
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
    "komunismus",
)

# Targeted historical overrides requested by the user.
IDEOLOGY_FLAG_OVERRIDES = {
    (
        "DEU",
        "autokracie",
    ): "https://commons.wikimedia.org/wiki/Special:FilePath/Flag%20of%20the%20German%20Empire.svg",
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
        "autokracie",
    ): "https://commons.wikimedia.org/wiki/Special:FilePath/Flag%20of%20Bohemia.svg",
    (
        "CZE",
        "fasismus",
    ): "https://commons.wikimedia.org/wiki/Special:FilePath/Flag%20of%20Czechoslovakia.svg",
    (
        "CZE",
        "komunismus",
    ): "https://commons.wikimedia.org/wiki/Special:FilePath/Flag%20of%20Czechoslovakia.svg",
    (
        "SWE",
        "kralovstvi",
    ): "https://commons.wikimedia.org/wiki/Special:FilePath/Naval%20Ensign%20of%20Sweden.svg",
    (
        "SWE",
        "autokracie",
    ): "https://commons.wikimedia.org/wiki/Special:FilePath/Naval%20Ensign%20of%20Sweden.svg",
    (
        "TUR",
        "autokracie",
    ): "https://commons.wikimedia.org/wiki/Special:FilePath/Flag%20of%20the%20Ottoman%20Empire.svg",
    (
        "TUR",
        "kralovstvi",
    ): "https://commons.wikimedia.org/wiki/Special:FilePath/Flag%20of%20the%20Ottoman%20Empire.svg",
    (
        "CZE",
        "kralovstvi",
    ): "https://commons.wikimedia.org/wiki/Special:FilePath/Flag%20of%20Bohemia.svg",
}

# Commons search hints for ideology-specific alternatives.
IDEOLOGY_SEARCH_TERMS: Dict[str, Tuple[str, ...]] = {
    "demokracie": ("republic", "civil", "constitutional", "modern"),
    "autokracie": ("empire", "imperial", "authoritarian", "tsardom", "caesar", "sultanate"),
    "kralovstvi": ("kingdom", "royal", "monarchy", "crown", "dynasty"),
    "fasismus": ("fascist", "fascism", "regime", "national", "corporat"),
    "nacismus": ("nazi", "national socialist", "third reich", "1935", "1933", "1941"),
    "komunismus": ("communist", "socialist", "people's republic", "soviet", "ussr", "workers"),
}

COUNTRY_TOKEN_STOPWORDS = {
    "the",
    "and",
    "of",
    "for",
    "state",
    "states",
    "republic",
    "kingdom",
    "federation",
    "federal",
    "people",
    "peoples",
    "democratic",
    "union",
    "islamic",
    "arab",
    "commonwealth",
}

UNSAFE_FLAG_TITLE_KEYWORDS = {
    "football",
    "soccer",
    "regulation",
    "commission",
    "party",
    "president",
    "municipal",
    "municipality",
    "city",
    "county",
    "province",
    "region",
    "department",
    "army",
    "navy",
    "air force",
    "police",
    "logo",
    "banner",
    "company",
    "railway",
    "fiction",
    "fictitious",
    "imaginary",
    "unofficial",
}

# Runtime guard: once Commons starts returning 429, skip further Commons lookups
# in this process and use safer fallbacks instead.
COMMONS_RATE_LIMITED = False
COMMONS_HISTORICAL_SECTION_CACHE: Dict[str, str] = {}

TARGET_YEAR_BY_IDEOLOGY: Dict[str, int] = {
    "demokracie": 2024,
    "autokracie": 1860,
    "kralovstvi": 1880,
    "fasismus": 1937,
    "nacismus": 1939,
    "komunismus": 1975,
}

MAX_YEAR_DISTANCE_BY_IDEOLOGY: Dict[str, int] = {
    "demokracie": 10_000,
    "autokracie": 120,
    "kralovstvi": 160,
    "fasismus": 20,
    "nacismus": 15,
    "komunismus": 40,
}

IDEOLOGY_FICTIONAL_COLORS: Dict[str, Tuple[str, str, str]] = {
    "demokracie": ("#1f5aa6", "#ffffff", "#cf2b3e"),
    "autokracie": ("#2f2f2f", "#7f1d1d", "#c9a227"),
    "kralovstvi": ("#1a2f80", "#f2f2f2", "#d4af37"),
    "fasismus": ("#111111", "#b22222", "#f2f2f2"),
    "nacismus": ("#202020", "#c1121f", "#ffffff"),
    "komunismus": ("#b80f0a", "#f4d03f", "#8b0000"),
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
        "komunismus": "komunismus",
        "komunista": "komunismus",
        "communism": "komunismus",
        "communist": "komunismus",
        "socialism": "komunismus",
        "socialist": "komunismus",
        "soviet": "komunismus",
    }

    if text in alias_map:
        # AI-EDITED
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


def build_iso_country_label_query(iso_codes: Sequence[str]) -> str:
    values = " ".join(f'"{code}"' for code in iso_codes)
    return (
        "SELECT ?iso3 ?countryLabel WHERE {\n"
        f"  VALUES ?iso3 {{ {values} }}\n"
        "  ?country wdt:P298 ?iso3.\n"
        "  SERVICE wikibase:label { bd:serviceParam wikibase:language \"en\". }\n"
        "}"
    )


def build_iso_flag_history_query(iso_codes: Sequence[str]) -> str:
    values = " ".join(f'"{code}"' for code in iso_codes)
    return (
        "SELECT ?iso3 ?flag ?start ?end WHERE {\n"
        f"  VALUES ?iso3 {{ {values} }}\n"
        "  ?country wdt:P298 ?iso3.\n"
        "  ?country p:P41 ?stmt.\n"
        "  ?stmt ps:P41 ?flag.\n"
        "  OPTIONAL { ?stmt pq:P580 ?start. }\n"
        "  OPTIONAL { ?stmt pq:P582 ?end. }\n"
        "}"
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


def fetch_json_url(url: str, timeout: int, retries: int = 3) -> Dict:
    global COMMONS_RATE_LIMITED
    last_error = None
    for attempt in range(retries):
        try:
            request = Request(
                url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "application/json",
                },
            )
            with urlopen(request, timeout=timeout) as response:
                payload = response.read().decode("utf-8")
            return json.loads(payload)
        except HTTPError as exc:
            if int(getattr(exc, "code", 0) or 0) == 429:
                COMMONS_RATE_LIMITED = True
                raise RuntimeError("commons_rate_limited") from exc
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(0.6 + (0.4 * attempt))
        except Exception as exc:
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(0.6 + (0.4 * attempt))

    raise RuntimeError(f"JSON request failed after retries: {last_error}")


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


def query_iso_country_labels(iso_codes: Sequence[str], timeout: int) -> Dict[str, str]:
    if not iso_codes:
        return {}

    payload = fetch_wdqs_json(build_iso_country_label_query(iso_codes), timeout=timeout)
    results = payload.get("results", {}).get("bindings", [])

    out: Dict[str, str] = {}
    for row in results:
        iso = normalize_iso3(row.get("iso3", {}).get("value", ""))
        label = str(row.get("countryLabel", {}).get("value", "")).strip()
        if iso and label and iso not in out:
            out[iso] = label

    return out


def parse_year_value(value: str) -> int:
    text = str(value or "").strip()
    if not text:
        return 0
    match = re.search(r"(-?\d{1,6})", text)
    if not match:
        return 0
    try:
        return int(match.group(1))
    except ValueError:
        return 0


def load_local_current_flags(path: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not os.path.exists(path):
        return out

    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                iso = normalize_iso3(row.get("iso3", "") or row.get("country_iso3", ""))
                url = str(
                    row.get("currentFlag", "")
                    or row.get("flag", "")
                    or row.get("source_url", "")
                    or ""
                ).strip()
                if iso and url and iso not in out:
                    out[iso] = url
    except Exception:
        return {}

    return out


def load_local_flag_history(path: str) -> Dict[str, List[Dict[str, int | str]]]:
    out: Dict[str, List[Dict[str, int | str]]] = {}
    if not os.path.exists(path):
        return out

    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                iso = normalize_iso3(row.get("iso3", "") or row.get("country_iso3", ""))
                url = str(row.get("flag", "") or row.get("source_url", "") or row.get("currentFlag", "") or "").strip()
                if not iso or not url:
                    continue
                start_year = parse_year_value(row.get("start", "") or row.get("start_year", ""))
                end_year = parse_year_value(row.get("end", "") or row.get("end_year", ""))
                out.setdefault(iso, []).append(
                    {
                        "source_url": url,
                        "start_year": start_year,
                        "end_year": end_year,
                    }
                )
    except Exception:
        return {}

    return out


def list_game_tag_candidates(iso3: str) -> List[str]:
    iso = normalize_iso3(iso3)
    candidates = [iso]
    candidates.extend(ISO3_GAME_TAG_ALIASES.get(iso, ()))
    return unique_keep_order([c for c in candidates if c])


def build_local_flag_index(source_dirs: Sequence[str]) -> Dict[str, Dict[str, object]]:
    index: Dict[str, Dict[str, object]] = {}
    for source_dir in source_dirs:
        if not os.path.isdir(source_dir):
            continue

        folder_name = os.path.basename(source_dir)
        for name in sorted(os.listdir(source_dir)):
            path = os.path.join(source_dir, name)
            if not os.path.isfile(path):
                continue

            stem, ext = os.path.splitext(name)
            if ext.lower() not in VALID_EXTENSIONS:
                continue

            tag = ""
            suffix = ""
            if "_" in stem:
                tag, suffix = stem.split("_", 1)
            else:
                tag = stem

            tag = normalize_iso3(tag)
            suffix = str(suffix or "").strip().lower()
            if not re.fullmatch(r"[A-Z0-9]{3}", tag):
                continue

            entry = index.setdefault(
                tag,
                {
                    "base": "",
                    "base_source": "",
                    "variants": {},
                },
            )

            if suffix:
                variants = entry.get("variants")
                if isinstance(variants, dict) and suffix not in variants:
                    variants[suffix] = {
                        "path": path,
                        "source": folder_name,
                    }
                continue

            # Keep first-found base image to preserve source directory priority.
            if not entry.get("base"):
                entry["base"] = path
                entry["base_source"] = folder_name

    return index


def resolve_local_flag_source(
    iso3: str,
    ideology: str,
    local_index: Dict[str, Dict[str, object]],
) -> Dict[str, str]:
    ideology_key = normalize_ideology(ideology)
    suffixes = IDEOLOGY_GAME_SUFFIXES.get(ideology_key, ())

    for tag in list_game_tag_candidates(iso3):
        entry = local_index.get(tag)
        if not entry:
            continue

        variants = entry.get("variants")
        if isinstance(variants, dict):
            for suffix in suffixes:
                item = variants.get(suffix)
                if isinstance(item, dict):
                    path = str(item.get("path", "") or "")
                    source = str(item.get("source", "") or "")
                    if path:
                        return {
                            "path": path,
                            "source": source,
                            "tag": tag,
                            "variant": suffix,
                        }

        base_path = str(entry.get("base", "") or "")
        base_source = str(entry.get("base_source", "") or "")
        if base_path:
            return {
                "path": base_path,
                "source": base_source,
                "tag": tag,
                "variant": "",
            }

    return {
        "path": "",
        "source": "",
        "tag": "",
        "variant": "",
    }


def merge_history_rows(
    primary_rows: Sequence[Dict[str, int | str]],
    fallback_rows: Sequence[Dict[str, int | str]],
) -> List[Dict[str, int | str]]:
    merged: List[Dict[str, int | str]] = []
    seen: Set[Tuple[str, int, int]] = set()

    for row in list(primary_rows) + list(fallback_rows):
        url = str(row.get("source_url", "") or "").strip()
        if not url:
            continue
        start_year = int(row.get("start_year", 0) or 0)
        end_year = int(row.get("end_year", 0) or 0)
        key = (normalize_source_identity(url), start_year, end_year)
        if key in seen:
            continue
        seen.add(key)
        merged.append(
            {
                "source_url": url,
                "start_year": start_year,
                "end_year": end_year,
            }
        )

    return merged


def query_iso_flag_history(iso_codes: Sequence[str], timeout: int) -> Dict[str, List[Dict[str, int | str]]]:
    if not iso_codes:
        return {}

    payload = fetch_wdqs_json(build_iso_flag_history_query(iso_codes), timeout=timeout)
    results = payload.get("results", {}).get("bindings", [])

    out: Dict[str, List[Dict[str, int | str]]] = {}
    for row in results:
        iso = normalize_iso3(row.get("iso3", {}).get("value", ""))
        url = str(row.get("flag", {}).get("value", "")).strip()
        start_year = parse_year_value(row.get("start", {}).get("value", ""))
        end_year = parse_year_value(row.get("end", {}).get("value", ""))
        if not iso or not url:
            continue
        out.setdefault(iso, []).append(
            {
                "source_url": url,
                "start_year": start_year,
                "end_year": end_year,
            }
        )

    return out


def select_historical_flag_for_ideology(
    history_rows: Sequence[Dict[str, int | str]],
    ideology: str,
    blocked_identities: Set[str],
    allow_blocked: bool = False,
    ignore_max_distance: bool = False,
) -> Tuple[str, str]:
    target_year = TARGET_YEAR_BY_IDEOLOGY.get(ideology, TARGET_YEAR_BY_IDEOLOGY["demokracie"])
    max_distance = MAX_YEAR_DISTANCE_BY_IDEOLOGY.get(ideology, 60)
    candidates: List[Tuple[int, str, int, int]] = []

    for row in history_rows:
        url = str(row.get("source_url", "") or "").strip()
        if not url:
            continue
        identity = normalize_source_identity(url)
        if not allow_blocked and identity and identity in blocked_identities:
            continue
        start_year = int(row.get("start_year", 0) or 0)
        end_year = int(row.get("end_year", 0) or 0)

        if start_year and end_year and start_year <= target_year <= end_year:
            distance = 0
        elif start_year and target_year < start_year:
            distance = start_year - target_year
        elif end_year and target_year > end_year:
            distance = target_year - end_year
        else:
            # No date qualifiers: keep as weak fallback.
            distance = 9999

        candidates.append((distance, url, start_year, end_year))

    if not candidates:
        return "", ""

    candidates.sort(key=lambda item: item[0])
    _, best_url, best_start, best_end = candidates[0]
    best_distance = candidates[0][0]
    if not ignore_max_distance and best_distance > max_distance:
        return "", ""
    if best_start and best_end:
        return best_url, f"wdqs_history_year:{target_year}:{best_start}-{best_end}"
    if best_start:
        return best_url, f"wdqs_history_year:{target_year}:from_{best_start}"
    if best_end:
        return best_url, f"wdqs_history_year:{target_year}:until_{best_end}"
    return best_url, f"wdqs_history_year:{target_year}:undated"


def normalize_source_identity(url: str) -> str:
    raw = str(url or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    path = unquote(parsed.path or "")
    file_name = os.path.basename(path).replace("_", " ").strip().lower()
    if file_name:
        return f"file|{file_name}"
    path_norm = path.replace("_", " ").strip().lower()
    return f"{parsed.netloc.lower()}|{path_norm}"


def is_low_quality_local_raster(path: str) -> bool:
    local_path = str(path or "").strip()
    if not local_path:
        return False

    cached = LOWRES_LOCAL_CACHE.get(local_path)
    if cached is not None:
        return cached

    ext = os.path.splitext(local_path)[1].lower()
    if ext == ".svg":
        LOWRES_LOCAL_CACHE[local_path] = False
        return False
    if ext not in VALID_EXTENSIONS:
        LOWRES_LOCAL_CACHE[local_path] = False
        return False
    if Image is None:
        LOWRES_LOCAL_CACHE[local_path] = False
        return False
    if not os.path.isfile(local_path):
        LOWRES_LOCAL_CACHE[local_path] = False
        return False

    try:
        with Image.open(local_path) as im:
            width, height = im.size
        lowres = width < LOCAL_MIN_RASTER_WIDTH or height < LOCAL_MIN_RASTER_HEIGHT
    except Exception:
        lowres = False

    LOWRES_LOCAL_CACHE[local_path] = lowres
    return lowres


def commons_filepath_url(file_title: str) -> str:
    clean = str(file_title or "").strip()
    if clean.lower().startswith("file:"):
        clean = clean[5:]
    return f"https://commons.wikimedia.org/wiki/Special:FilePath/{quote(clean)}"


def is_valid_file_title(title: str) -> bool:
    value = str(title or "").strip()
    if not value.lower().startswith("file:"):
        return False
    _, ext = os.path.splitext(value)
    return ext.lower() in VALID_EXTENSIONS


def tokenize_country_label(country_label: str) -> List[str]:
    tokens = [tok for tok in re.split(r"[^a-z0-9]+", str(country_label or "").lower()) if len(tok) >= 4]
    return [tok for tok in tokens if tok not in COUNTRY_TOKEN_STOPWORDS]


def strip_wiki_markup(text: str) -> str:
    value = str(text or "")
    value = re.sub(r"\[\[(?:[^\]|]+\|)?([^\]]+)\]\]", r"\1", value)
    value = re.sub(r"\[https?://[^\s\]]+\s+([^\]]+)\]", r"\1", value)
    value = value.replace("'", "")
    return value.strip()


def section_title_tokens(title: str) -> Set[str]:
    return set(tokenize_country_label(strip_wiki_markup(title)))


def load_historical_europe_sections(timeout: int) -> Dict[str, str]:
    global COMMONS_HISTORICAL_SECTION_CACHE
    if COMMONS_HISTORICAL_SECTION_CACHE:
        return COMMONS_HISTORICAL_SECTION_CACHE

    if COMMONS_RATE_LIMITED:
        return {}

    params = urlencode(
        {
            "action": "parse",
            "format": "json",
            "page": COMMONS_HISTORICAL_EUROPE_PAGE,
            "prop": "wikitext",
        }
    )
    payload = fetch_json_url(f"{COMMONS_API_URL}?{params}", timeout=timeout)
    raw = str(payload.get("parse", {}).get("wikitext", {}).get("*", ""))
    if not raw:
        return {}

    matches = list(re.finditer(r"^==\s*([^=\n]+?)\s*==\s*$", raw, flags=re.MULTILINE))
    sections: Dict[str, str] = {}
    for idx, match in enumerate(matches):
        title = strip_wiki_markup(match.group(1))
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(raw)
        sections[title] = raw[start:end]

    COMMONS_HISTORICAL_SECTION_CACHE = sections
    return sections


def historical_europe_gallery_candidates(country_label: str, timeout: int) -> List[Tuple[str, str]]:
    country_tokens = set(tokenize_country_label(country_label))
    if not country_tokens:
        return []

    sections = load_historical_europe_sections(timeout=timeout)
    if not sections:
        return []

    best_title = ""
    best_overlap = 0
    for title in sections:
        overlap = len(country_tokens & section_title_tokens(title))
        if overlap > best_overlap:
            best_overlap = overlap
            best_title = title

    if best_overlap == 0 or not best_title:
        return []

    body = sections.get(best_title, "")
    out: List[Tuple[str, str]] = []
    for file_name in re.findall(r"\[\[(?:File|Soubor):([^\]|]+)", body, flags=re.IGNORECASE):
        name = str(file_name).strip()
        if not name:
            continue
        lower_name = name.lower()
        if any(k in lower_name for k in UNSAFE_FLAG_TITLE_KEYWORDS):
            continue
        out.append((f"File:{name}", f"gallery_europe:{best_title}:File:{name}"))

    return unique_keep_order(out)


def is_plausible_country_flag_title(
    title: str,
    country_tokens: Sequence[str],
    foreign_tokens: Set[str],
    allow_country_miss: bool = False,
) -> bool:
    text = str(title or "").lower().strip()
    if not text.startswith("file:"):
        return False

    # Keep the scope to actual flags, but allow common title forms beyond
    # strictly "Flag of ..." (e.g. state/civil/naval/war variants).
    if "flag" not in text:
        return False

    if any(keyword in text for keyword in UNSAFE_FLAG_TITLE_KEYWORDS):
        return False

    title_tokens = {tok for tok in re.split(r"[^a-z0-9]+", text) if tok}
    if country_tokens and not allow_country_miss and not any(tok in title_tokens for tok in country_tokens):
        return False

    if any(tok in title_tokens for tok in foreign_tokens):
        return False

    return True


def score_flag_candidate(title: str, country_tokens: Sequence[str], ideology: str) -> int:
    lower_title = str(title or "").lower()
    title_tokens = {tok for tok in re.split(r"[^a-z0-9]+", lower_title) if tok}
    score = 0

    for tok in country_tokens:
        if tok in title_tokens:
            score += 3

    for term in IDEOLOGY_SEARCH_TERMS.get(ideology, ()):
        term_tokens = [tok for tok in re.split(r"[^a-z0-9]+", term.lower()) if tok]
        if term_tokens and any(tok in title_tokens for tok in term_tokens):
            score += 4

    if any(year in lower_title for year in ("1917", "1922", "1945", "1948", "1989")):
        score += 1

    if "historical" in lower_title:
        score += 1

    return score


def choose_best_candidate(
    candidates: Sequence[Tuple[str, str]],
    country_tokens: Sequence[str],
    foreign_tokens: Set[str],
    ideology: str,
    blocked_identities: Set[str],
) -> Tuple[str, str]:
    ranked: List[Tuple[int, str, str]] = []
    for title, note in candidates:
        if not is_valid_file_title(title):
            continue
        allow_country_miss = str(note).startswith("gallery_europe:")
        if not is_plausible_country_flag_title(
            title,
            country_tokens=country_tokens,
            foreign_tokens=foreign_tokens,
            allow_country_miss=allow_country_miss,
        ):
            continue
        candidate_url = commons_filepath_url(title)
        candidate_identity = normalize_source_identity(candidate_url)
        if candidate_identity and candidate_identity in blocked_identities:
            continue
        score = score_flag_candidate(title, country_tokens=country_tokens, ideology=ideology)
        ranked.append((score, title, note))

    if not ranked:
        return "", ""

    ranked.sort(key=lambda item: item[0], reverse=True)
    best_score, best_title, best_note = ranked[0]
    if best_score < 4:
        return "", ""
    return commons_filepath_url(best_title), best_note


def query_commons_category_files(country_label: str, timeout: int) -> List[str]:
    country = str(country_label or "").strip()
    if not country:
        return []

    category_names = [
        f"Historical flags of {country}",
        f"Flags of {country}",
    ]

    out: List[str] = []
    for category in category_names:
        try:
            params = urlencode(
                {
                    "action": "query",
                    "format": "json",
                    "list": "categorymembers",
                    "cmtitle": f"Category:{category}",
                    "cmtype": "file",
                    "cmlimit": "100",
                }
            )
            payload = fetch_json_url(f"{COMMONS_API_URL}?{params}", timeout=timeout)
        except Exception:
            continue

        members = payload.get("query", {}).get("categorymembers", [])
        for item in members:
            title = str(item.get("title") or "").strip()
            if title:
                out.append(title)

    return unique_keep_order(out)


def search_commons_ideology_flag(
    country_label: str,
    ideology: str,
    timeout: int,
    blocked_identities: Set[str],
    foreign_tokens: Set[str],
) -> Tuple[str, str]:
    if COMMONS_RATE_LIMITED:
        return "", ""

    country = str(country_label or "").strip()
    if not country:
        return "", ""
    country_tokens = tokenize_country_label(country)

    terms = IDEOLOGY_SEARCH_TERMS.get(ideology, (ideology.replace("_", " "),))
    gathered: List[Tuple[str, str]] = []

    for term in terms:
        queries = [
            f'intitle:"Flag of {country}" {term}',
            f'intitle:"Flag of the {country}" {term}',
            f'incategory:"Historical flags of {country}" {term}',
            f'incategory:"Flags of {country}" {term}',
        ]
        for query in queries:
            try:
                params = urlencode(
                    {
                        "action": "query",
                        "format": "json",
                        "list": "search",
                        "srnamespace": "6",
                        "srlimit": "20",
                        "srsearch": query,
                    }
                )
                payload = fetch_json_url(f"{COMMONS_API_URL}?{params}", timeout=timeout)
            except Exception:
                continue

            entries = payload.get("query", {}).get("search", [])

            for row in entries:
                title = str(row.get("title") or "").strip()
                if not is_valid_file_title(title):
                    continue
                title_tokens = {tok for tok in re.split(r"[^a-z0-9]+", title.lower()) if tok}
                if country_tokens and not any(tok in title_tokens for tok in country_tokens):
                    continue
                gathered.append((title, f"commons_search:{term}:{title}"))

    for title in query_commons_category_files(country_label=country, timeout=timeout):
        gathered.append((title, f"commons_category:{title}"))

    for title, note in historical_europe_gallery_candidates(country_label=country, timeout=timeout):
        gathered.append((title, note))

    return choose_best_candidate(
        candidates=gathered,
        country_tokens=country_tokens,
        foreign_tokens=foreign_tokens,
        ideology=ideology,
        blocked_identities=blocked_identities,
    )


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


def pick_preferred_flag_file(paths: Sequence[str]) -> str:
    if not paths:
        return ""
    ext_rank = {
        ".svg": 0,
        ".png": 1,
        ".jpg": 2,
        ".jpeg": 3,
        ".webp": 4,
        ".gif": 5,
    }
    return sorted(paths, key=lambda p: (ext_rank.get(os.path.splitext(p)[1].lower(), 99), p))[0]


def get_base_flag_file_for_iso(iso: str) -> str:
    stem = os.path.join(DEFAULT_OUT_DIR, iso)
    candidates = existing_flag_files(stem)
    return pick_preferred_flag_file(candidates)


def download_flag(url: str, stem_path: str, timeout: int, retries: int = 3) -> Dict[str, str]:
    local_candidate = str(url or "").strip()
    if local_candidate and os.path.isfile(local_candidate):
        ext = os.path.splitext(local_candidate)[1].lower()
        if ext not in VALID_EXTENSIONS:
            ext = ".png"
        out_path = stem_path + ext
        tmp_path = out_path + ".tmp"
        shutil.copyfile(local_candidate, tmp_path)
        os.replace(tmp_path, out_path)
        return {
            "path": out_path,
            "source_url": local_candidate,
        }

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


def write_fictional_flag_svg(stem_path: str, iso: str, ideology: str) -> str:
        colors = IDEOLOGY_FICTIONAL_COLORS.get(ideology, ("#3a3a3a", "#f0f0f0", "#0f5aa0"))
        width = 900
        height = 600

        # Three horizontal stripes + central emblem circle + short label.
        svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
    <rect width="{width}" height="{height}" fill="{colors[0]}"/>
    <rect y="{height // 3}" width="{width}" height="{height // 3}" fill="{colors[1]}"/>
    <rect y="{(height // 3) * 2}" width="{width}" height="{height // 3}" fill="{colors[2]}"/>
    <circle cx="{width // 2}" cy="{height // 2}" r="92" fill="#ffffff" fill-opacity="0.85"/>
    <circle cx="{width // 2}" cy="{height // 2}" r="72" fill="{colors[2]}"/>
    <text x="{width // 2}" y="{(height // 2) + 14}" text-anchor="middle" font-size="42" font-family="Arial, sans-serif" fill="#ffffff">{escape(iso)}</text>
    <text x="24" y="{height - 20}" font-size="24" font-family="Arial, sans-serif" fill="#ffffff" fill-opacity="0.9">{escape(ideology)}</text>
</svg>'''

        out_path = stem_path + ".svg"
        tmp_path = out_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as handle:
                handle.write(svg)
        os.replace(tmp_path, out_path)
        return out_path


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
    existing_map: Dict[str, Dict[str, str]] = {}
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle, delimiter=";")
                for row in reader:
                    iso = normalize_iso3(row.get("country_iso3", ""))
                    if iso:
                        existing_map[iso] = {
                            "country_iso3": iso,
                            "flag_file": str(row.get("flag_file", "") or ""),
                            "source_url": str(row.get("source_url", "") or ""),
                            "status": str(row.get("status", "") or ""),
                            "note": str(row.get("note", "") or ""),
                        }
        except Exception:
            existing_map = {}

    update_map: Dict[str, Dict[str, str]] = {}
    for row in rows:
        iso = normalize_iso3(row.get("country_iso3", ""))
        if not iso:
            continue
        update_map[iso] = {
            "country_iso3": iso,
            "flag_file": str(row.get("flag_file", "") or ""),
            "source_url": str(row.get("source_url", "") or ""),
            "status": str(row.get("status", "") or ""),
            "note": str(row.get("note", "") or ""),
        }

    merged_map = dict(existing_map)
    merged_map.update(update_map)
    merged_rows = [merged_map[k] for k in sorted(merged_map)]

    ensure_parent_dir(path)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(["country_iso3", "flag_file", "source_url", "status", "note"])
        for row in merged_rows:
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
    existing_map: Dict[Tuple[str, str], Dict[str, str]] = {}
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle, delimiter=";")
                for row in reader:
                    iso = normalize_iso3(row.get("country_iso3", ""))
                    ideology = normalize_ideology(row.get("ideology", ""))
                    if iso and ideology:
                        existing_map[(iso, ideology)] = {
                            "country_iso3": iso,
                            "ideology": ideology,
                            "flag_file": str(row.get("flag_file", "") or ""),
                            "source_url": str(row.get("source_url", "") or ""),
                            "status": str(row.get("status", "") or ""),
                            "note": str(row.get("note", "") or ""),
                        }
        except Exception:
            existing_map = {}

    update_map: Dict[Tuple[str, str], Dict[str, str]] = {}
    for row in rows:
        iso = normalize_iso3(row.get("country_iso3", ""))
        ideology = normalize_ideology(row.get("ideology", ""))
        if not iso or not ideology:
            continue
        update_map[(iso, ideology)] = {
            "country_iso3": iso,
            "ideology": ideology,
            "flag_file": str(row.get("flag_file", "") or ""),
            "source_url": str(row.get("source_url", "") or ""),
            "status": str(row.get("status", "") or ""),
            "note": str(row.get("note", "") or ""),
        }

    merged_map = dict(existing_map)
    merged_map.update(update_map)
    merged_rows = [merged_map[k] for k in sorted(merged_map, key=lambda t: (t[0], t[1]))]

    ensure_parent_dir(path)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(["country_iso3", "ideology", "flag_file", "source_url", "status", "note"])
        for row in merged_rows:
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
    local_index = build_local_flag_index(LOCAL_FLAG_SOURCE_DIRS)
    local_current_by_iso = load_local_current_flags(LOCAL_FLAG_CURRENT_PATH)
    local_history_by_iso = load_local_flag_history(LOCAL_FLAG_HISTORY_PATH)

    need_url_codes: List[str] = []
    need_history_codes: List[str] = []

    for iso in iso_codes:
        source_key = REQUEST_ISO_OVERRIDES.get(iso, iso)
        local_folder_base = resolve_local_flag_source(iso, "demokracie", local_index)
        local_current = local_current_by_iso.get(iso) or local_current_by_iso.get(source_key)
        local_history = local_history_by_iso.get(iso) or local_history_by_iso.get(source_key) or []
        if not local_current and not local_folder_base.get("path"):
            need_url_codes.append(source_key)
        if not local_history:
            need_history_codes.append(source_key)

    iso_to_url = query_iso_flag_urls(unique_keep_order(need_url_codes), timeout=timeout) if need_url_codes else {}
    history_by_iso = query_iso_flag_history(unique_keep_order(need_history_codes), timeout=timeout) if need_history_codes else {}

    out: Dict[str, Dict[str, str]] = {}
    for iso in iso_codes:
        source_key = REQUEST_ISO_OVERRIDES.get(iso, iso)
        local_folder_base = resolve_local_flag_source(iso, "demokracie", local_index)
        source_url = str(local_folder_base.get("path", "") or "")
        note = ""
        local_history = list(local_history_by_iso.get(iso) or local_history_by_iso.get(source_key) or [])
        remote_history = list(history_by_iso.get(source_key, []))
        history = merge_history_rows(local_history, remote_history)

        if source_url:
            note = f"local_folder_current:{local_folder_base.get('source', '')}"
            if local_folder_base.get("tag") and local_folder_base.get("tag") != iso:
                note = join_notes(note, f"tag_alias:{iso}->{local_folder_base.get('tag')}")
        else:
            source_url = local_current_by_iso.get(iso) or local_current_by_iso.get(source_key) or ""
            if source_url:
                note = "local_csv_current"
            else:
                source_url = iso_to_url.get(source_key, "")

        if source_url and source_key != iso:
            note = join_notes(note, f"iso_alias:{iso}->{source_key}")
        elif not source_url and iso in MANUAL_QID_FALLBACK:
            source_url = query_flag_url_for_qid(MANUAL_QID_FALLBACK[iso], timeout=timeout)
            if source_url:
                note = join_notes(note, f"fallback_qid:{MANUAL_QID_FALLBACK[iso]}")

        if local_history:
            note = join_notes(note, "local_csv_history")

        local_variants: Dict[str, str] = {}
        local_variant_notes: Dict[str, str] = {}
        for ideology in DEFAULT_VARIANT_IDEOLOGIES:
            local_variant = resolve_local_flag_source(iso, ideology, local_index)
            variant_path = str(local_variant.get("path", "") or "")
            if not variant_path:
                continue
            local_variants[ideology] = variant_path
            variant_note = f"local_folder_variant:{local_variant.get('source', '')}"
            if local_variant.get("variant"):
                variant_note = join_notes(variant_note, f"variant:{local_variant.get('variant')}")
            if local_variant.get("tag") and local_variant.get("tag") != iso:
                variant_note = join_notes(variant_note, f"tag_alias:{iso}->{local_variant.get('tag')}")
            local_variant_notes[ideology] = variant_note

        out[iso] = {
            "source_url": source_url,
            "note": note,
            "history": history,
            "local_variants": local_variants,
            "local_variant_notes": local_variant_notes,
        }

    return out


def choose_ideology_source_url(
    iso: str,
    ideology: str,
    base_source: Dict[str, str],
    country_label: str,
    timeout: int,
    blocked_identities: Set[str],
    foreign_tokens: Set[str],
    use_commons_search: bool,
) -> Tuple[str, str]:
    local_variants = base_source.get("local_variants", {})
    local_variant_notes = base_source.get("local_variant_notes", {})
    lowres_local_variant_url = ""
    lowres_local_variant_note = ""
    if isinstance(local_variants, dict):
        local_variant_url = str(local_variants.get(ideology, "") or "").strip()
        if local_variant_url:
            local_note = ""
            if isinstance(local_variant_notes, dict):
                local_note = str(local_variant_notes.get(ideology, "") or "").strip()

            # For non-democracy ideologies, semantic correctness has priority.
            # Use local HOI4/VIC2 ideology variants first even if low-res.
            if ideology != "demokracie":
                local_identity = normalize_source_identity(local_variant_url)
                if local_identity in blocked_identities:
                    return local_variant_url, join_notes(local_note, "local_duplicate_ok")
                return local_variant_url, join_notes(local_note, "local_variant_primary")

            # Very small local rasters (e.g. HOI4 82x52) are kept only as last-resort fallback.
            if is_low_quality_local_raster(local_variant_url):
                lowres_local_variant_url = local_variant_url
                lowres_local_variant_note = join_notes(local_note, "local_lowres_deferred")
            else:
                # Local curated files are preferred even when repeated across ideologies.
                local_identity = normalize_source_identity(local_variant_url)
                if local_identity in blocked_identities:
                    return local_variant_url, join_notes(local_note, "local_duplicate_ok")
                return local_variant_url, join_notes(local_note)

    override_url = IDEOLOGY_FLAG_OVERRIDES.get((iso, ideology), "")
    override_identity = normalize_source_identity(override_url)
    if override_url and override_identity not in blocked_identities:
        return override_url, "historical_override"

    base_url = str(base_source.get("source_url", "") or "").strip()
    base_note = str(base_source.get("note", "") or "").strip()
    base_identity = normalize_source_identity(base_url)
    base_parsed = urlparse(base_url)
    base_is_local_file = bool(base_url) and base_parsed.scheme.lower() not in ("http", "https")
    base_is_lowres_local = base_is_local_file and is_low_quality_local_raster(base_url)

    # Current/default regime should always use the current country flag.
    if ideology == "demokracie" and base_url and base_identity not in blocked_identities:
        if not base_is_lowres_local:
            return base_url, join_notes("fallback_base_flag", base_note)

    # When a country has only a local base file (no ideology variants), keep local-first behavior.
    if ideology != "demokracie" and base_is_local_file and base_url:
        if not base_is_lowres_local:
            if base_identity in blocked_identities:
                return base_url, join_notes("fallback_base_local_duplicate_ok", base_note)
            return base_url, join_notes("fallback_base_local", base_note)

    history_rows = base_source.get("history", [])
    if isinstance(history_rows, list):
        historical_url, historical_note = select_historical_flag_for_ideology(
            history_rows=history_rows,
            ideology=ideology,
            blocked_identities=blocked_identities,
        )
        if historical_url:
            return historical_url, historical_note

        # Step 2: keep uniqueness, but ignore year distance.
        relaxed_unique_url, relaxed_unique_note = select_historical_flag_for_ideology(
            history_rows=history_rows,
            ideology=ideology,
            blocked_identities=blocked_identities,
            ignore_max_distance=True,
        )
        if relaxed_unique_url:
            return relaxed_unique_url, join_notes(relaxed_unique_note, "fallback_relaxed_unique")

    if ideology != "demokracie" and bool(use_commons_search):
        candidate_url, candidate_note = search_commons_ideology_flag(
            country_label=country_label,
            ideology=ideology,
            timeout=timeout,
            blocked_identities=blocked_identities,
            foreign_tokens=foreign_tokens,
        )
        if candidate_url:
            return candidate_url, candidate_note

    if base_url and base_identity not in blocked_identities:
        if not base_is_lowres_local:
            return base_url, join_notes("fallback_base_flag", base_note)

    # Before giving up, allow deferred low-resolution local variant.
    if lowres_local_variant_url:
        local_identity = normalize_source_identity(lowres_local_variant_url)
        if local_identity in blocked_identities:
            return lowres_local_variant_url, join_notes(lowres_local_variant_note, "local_duplicate_ok")
        return lowres_local_variant_url, join_notes(lowres_local_variant_note, "fallback_lowres_local")

    # Step 5: if nothing else exists, allow historical duplicates as a last resort.
    if isinstance(history_rows, list):
        relaxed_duplicate_url, relaxed_duplicate_note = select_historical_flag_for_ideology(
            history_rows=history_rows,
            ideology=ideology,
            blocked_identities=blocked_identities,
            allow_blocked=True,
            ignore_max_distance=True,
        )
        if relaxed_duplicate_url:
            return relaxed_duplicate_url, join_notes(relaxed_duplicate_note, "fallback_relaxed_duplicate")

    if base_url:
        if base_is_lowres_local:
            return base_url, join_notes("fallback_base_duplicate_ok", base_note, "fallback_lowres_local")
        return base_url, join_notes("fallback_base_duplicate_ok", base_note)

    # For non-democratic variants, prefer fictional generation over forced duplicate reuse.
    if ideology != "demokracie" and base_url:
        return "", join_notes("no_safe_distinct_source")

    if override_url:
        return override_url, join_notes("historical_override", "duplicate_source_unresolved")

    if base_url:
        return base_url, join_notes("fallback_base_flag", base_note, "duplicate_source_unresolved")

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
    allow_fictional: bool,
    use_commons_search: bool,
) -> int:
    os.makedirs(out_dir, exist_ok=True)

    source_by_iso = resolve_flag_sources(iso_codes, timeout=timeout)
    try:
        country_label_by_iso = query_iso_country_labels(iso_codes, timeout=timeout)
    except Exception:
        country_label_by_iso = {}

    manifest_rows: List[Dict[str, str]] = []
    downloaded = 0
    reused = 0
    missing = 0
    total = len(iso_codes) * len(ideologies)
    step = 0

    for iso in iso_codes:
        base_source = source_by_iso.get(iso, {})
        base_set_file = get_base_flag_file_for_iso(iso)
        country_label = country_label_by_iso.get(iso, "")
        current_tokens = set(tokenize_country_label(country_label))
        foreign_tokens: Set[str] = set()
        for other_iso, other_label in country_label_by_iso.items():
            if other_iso == iso:
                continue
            for tok in tokenize_country_label(other_label):
                if tok not in current_tokens:
                    foreign_tokens.add(tok)
        used_identities: Set[str] = set()
        downloaded_for_iso: List[str] = []
        for ideology in ideologies:
            step += 1
            stem = os.path.join(out_dir, f"{iso}__{ideology}")
            existing = existing_flag_files(stem)

            # Democracy variant is anchored to the base flag set, not ideology search/history.
            if ideology == "demokracie" and base_set_file and os.path.isfile(base_set_file):
                try:
                    copy_result = download_flag(base_set_file, stem, timeout=timeout)
                    out_path = copy_result["path"]
                    final_url = copy_result["source_url"]

                    for old_path in existing_flag_files(stem):
                        if old_path != out_path:
                            try:
                                os.remove(old_path)
                            except OSError:
                                pass

                    downloaded += 1
                    downloaded_for_iso.append(out_path)
                    final_identity = normalize_source_identity(final_url)
                    if final_identity:
                        used_identities.add(final_identity)
                    manifest_rows.append(
                        {
                            "country_iso3": iso,
                            "ideology": ideology,
                            "flag_file": os.path.basename(out_path),
                            "source_url": final_url,
                            "status": "downloaded",
                            "note": "democracy_from_base_set",
                        }
                    )
                    print(f"[FLAGS] {step}/{total} {iso} {ideology}: {os.path.basename(out_path)} (base set)")
                    time.sleep(0.1)
                    continue
                except Exception as exc:
                    # If base-set copy fails, continue into standard ideology flow.
                    print(f"[FLAGS] {step}/{total} {iso} {ideology}: base-set copy failed ({exc}), trying standard flow")

            if existing and not force:
                reused += 1
                selected_identity = normalize_source_identity(existing[0])
                if selected_identity:
                    used_identities.add(selected_identity)
                manifest_rows.append(
                    {
                        "country_iso3": iso,
                        "ideology": ideology,
                        "flag_file": os.path.basename(existing[0]),
                        "source_url": "",
                        "status": "existing",
                        "note": "kept_existing_file",
                    }
                )
                continue

            source_url, source_note = choose_ideology_source_url(
                iso=iso,
                ideology=ideology,
                base_source=base_source,
                country_label=country_label,
                timeout=timeout,
                blocked_identities=used_identities,
                foreign_tokens=foreign_tokens,
                use_commons_search=use_commons_search,
            )

            if not source_url:
                if allow_fictional:
                    try:
                        out_path = write_fictional_flag_svg(stem, iso, ideology)
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
                                "source_url": "fictional://generated",
                                "status": "generated",
                                "note": "fictional_fallback_no_source",
                            }
                        )
                        print(f"[FLAGS] {step}/{total} {iso} {ideology}: {os.path.basename(out_path)} (fictional)")
                    except Exception as exc:
                        missing += 1
                        manifest_rows.append(
                            {
                                "country_iso3": iso,
                                "ideology": ideology,
                                "flag_file": "",
                                "source_url": "",
                                "status": "missing",
                                "note": f"no_flag_url_found|fictional_error:{exc}",
                            }
                        )
                        print(f"[FLAGS] {step}/{total} {iso} {ideology}: missing URL")
                else:
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
                downloaded_for_iso.append(out_path)
                final_identity = normalize_source_identity(final_url)
                if final_identity:
                    used_identities.add(final_identity)
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
                local_direct_fallback = ""
                local_variants_map = base_source.get("local_variants", {})
                if isinstance(local_variants_map, dict):
                    local_direct_fallback = str(local_variants_map.get(ideology, "") or "").strip()

                if not local_direct_fallback:
                    base_local_candidate = str(base_source.get("source_url", "") or "").strip()
                    parsed_base = urlparse(base_local_candidate)
                    if base_local_candidate and parsed_base.scheme.lower() not in ("http", "https"):
                        local_direct_fallback = base_local_candidate

                if local_direct_fallback and os.path.isfile(local_direct_fallback):
                    try:
                        fallback_result = download_flag(local_direct_fallback, stem, timeout=timeout)
                        out_path = fallback_result["path"]
                        final_url = fallback_result["source_url"]

                        for old_path in existing_flag_files(stem):
                            if old_path != out_path:
                                try:
                                    os.remove(old_path)
                                except OSError:
                                    pass

                        downloaded += 1
                        downloaded_for_iso.append(out_path)
                        final_identity = normalize_source_identity(final_url)
                        if final_identity:
                            used_identities.add(final_identity)
                        manifest_rows.append(
                            {
                                "country_iso3": iso,
                                "ideology": ideology,
                                "flag_file": os.path.basename(out_path),
                                "source_url": final_url,
                                "status": "downloaded",
                                "note": join_notes(source_note, "fallback_local_after_error", f"download_error:{exc}"),
                            }
                        )
                        print(f"[FLAGS] {step}/{total} {iso} {ideology}: {os.path.basename(out_path)} (local fallback)")
                        time.sleep(0.1)
                        continue
                    except Exception:
                        pass

                if downloaded_for_iso:
                    try:
                        fallback_src = downloaded_for_iso[-1]
                        fallback_ext = os.path.splitext(fallback_src)[1].lower()
                        if fallback_ext not in VALID_EXTENSIONS:
                            fallback_ext = ".png"
                        fallback_out = stem + fallback_ext
                        fallback_tmp = fallback_out + ".tmp"
                        shutil.copyfile(fallback_src, fallback_tmp)
                        os.replace(fallback_tmp, fallback_out)

                        for old_path in existing_flag_files(stem):
                            if old_path != fallback_out:
                                try:
                                    os.remove(old_path)
                                except OSError:
                                    pass

                        downloaded += 1
                        downloaded_for_iso.append(fallback_out)
                        fallback_identity = normalize_source_identity(fallback_out)
                        if fallback_identity:
                            used_identities.add(fallback_identity)
                        manifest_rows.append(
                            {
                                "country_iso3": iso,
                                "ideology": ideology,
                                "flag_file": os.path.basename(fallback_out),
                                "source_url": fallback_src,
                                "status": "downloaded",
                                "note": join_notes(source_note, f"fallback_local_copy:{os.path.basename(fallback_src)}", f"download_error:{exc}"),
                            }
                        )
                        print(f"[FLAGS] {step}/{total} {iso} {ideology}: {os.path.basename(fallback_out)} (fallback copy)")
                        time.sleep(0.1)
                        continue
                    except Exception:
                        pass

                if allow_fictional:
                    try:
                        out_path = write_fictional_flag_svg(stem, iso, ideology)
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
                                "source_url": "fictional://generated",
                                "status": "generated",
                                "note": f"fictional_fallback_download_error:{exc}",
                            }
                        )
                        print(f"[FLAGS] {step}/{total} {iso} {ideology}: {os.path.basename(out_path)} (fictional)")
                    except Exception as second_exc:
                        missing += 1
                        manifest_rows.append(
                            {
                                "country_iso3": iso,
                                "ideology": ideology,
                                "flag_file": "",
                                "source_url": source_url,
                                "status": "error",
                                "note": f"{exc}|fictional_error:{second_exc}",
                            }
                        )
                        print(f"[FLAGS] {step}/{total} {iso} {ideology}: ERROR {exc}")
                else:
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
    parser.add_argument(
        "--allow-fictional",
        action="store_true",
        help="Allow generated fictional fallback flags when no valid source is available.",
    )
    parser.add_argument(
        "--use-commons-search",
        action="store_true",
        help="Enable Commons text/category search fallback (less strict, can be noisy).",
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
            allow_fictional=bool(args.allow_fictional),
            use_commons_search=bool(args.use_commons_search),
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
