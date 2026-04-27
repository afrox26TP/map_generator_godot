# AI-GENERATED
import os
import re
import json
import unicodedata
from typing import Dict, List, Optional, Set, Tuple

import geopandas as gpd
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
COUNTRY_RELATIONSHIPS_PATH = os.path.join(BASE, "country_relationships_totals.csv")
COUNTRY_RELATIONSHIPS_STARTER_PATH = os.path.join(
    BASE,
    "country_relationships_totals_starter.csv",
)
OUT_DIR = os.path.join(BASE, "opengs_export")
OUT_PATH = os.path.join(OUT_DIR, "Relationships.csv")
COUNTRY_OUT_PATH = os.path.join(OUT_DIR, "CountryRelationships.csv")
TEMPLATE_OUT_PATH = os.path.join(OUT_DIR, "RelationshipsTemplate.json")
TARGET_RELATIONSHIP_YEAR = 2025


def normalize_iso(value: Optional[str]) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().upper().replace(" ", "")


def normalize_text(value: Optional[str]) -> str:
    if value is None:
        return ""

    text = str(value).strip().lower()
    if not text:
        return ""

    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return text.strip()


def parse_number(value) -> Optional[float]:
    if value is None:
        return None

    if isinstance(value, (int, float)):
        out = float(value)
        return out if pd.notna(out) else None

    txt = str(value).strip()
    if not txt:
        return None

    txt = txt.replace(" ", "").replace("_", "")
    txt = re.sub(r"[^0-9,.-]", "", txt)

    if "," in txt and "." in txt:
        if txt.rfind(",") > txt.rfind("."):
            txt = txt.replace(".", "").replace(",", ".")
        else:
            txt = txt.replace(",", "")
    elif "," in txt:
        txt = txt.replace(",", ".")

    num = pd.to_numeric(txt, errors="coerce")
    if pd.isna(num):
        return None

    return float(num)


def clamp_score(score: float) -> float:
    return max(-100.0, min(100.0, float(score)))


def _resolve_input_path() -> Optional[str]:
    for path in (COUNTRY_RELATIONSHIPS_PATH, COUNTRY_RELATIONSHIPS_STARTER_PATH):
        if os.path.exists(path):
            return path
    return None


def _build_name_to_iso_lookup(land: gpd.GeoDataFrame) -> Dict[str, str]:
    lookup: Dict[str, str] = {}
    if "country" not in land.columns:
        return lookup

    for _, row in land[["country", "admin"]].drop_duplicates().iterrows():
        iso = normalize_iso(row.get("country"))
        if not iso:
            continue

        lookup[normalize_text(iso)] = iso
        admin_name = normalize_text(row.get("admin"))
        if admin_name:
            lookup[admin_name] = iso

    return lookup


def _parse_country_ref(value: object, lookup: Dict[str, str], land_isos: Set[str]) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""

    iso = normalize_iso(raw)
    if re.fullmatch(r"[A-Za-z]{3}", iso) and iso in land_isos:
        return iso

    return lookup.get(normalize_text(raw), "")


def _build_country_ideology_lookup(
    ideology_rows: Optional[List[Dict[str, object]]],
) -> Dict[str, str]:
    if not ideology_rows:
        return {}

    tmp: Dict[str, Dict[str, int]] = {}
    for row in ideology_rows:
        iso = normalize_iso(row.get("country_iso3"))
        ideology = str(row.get("ideology") or "unknown").strip().lower()
        if not iso:
            continue
        tmp.setdefault(iso, {})
        tmp[iso][ideology] = tmp[iso].get(ideology, 0) + 1

    out: Dict[str, str] = {}
    for iso, counts in tmp.items():
        out[iso] = max(counts.items(), key=lambda item: item[1])[0]
    return out


def _build_country_gdp_pc_lookup(
    gdp_rows: Optional[List[Dict[str, object]]],
) -> Dict[str, float]:
    if not gdp_rows:
        return {}

    totals: Dict[str, Dict[str, float]] = {}
    for row in gdp_rows:
        iso = normalize_iso(row.get("country_iso3"))
        if not iso:
            continue

        gdp = float(row.get("gdp") or 0.0)
        pop = float(row.get("population") or 0.0)

        bucket = totals.setdefault(iso, {"gdp": 0.0, "pop": 0.0})
        bucket["gdp"] += max(gdp, 0.0)
        bucket["pop"] += max(pop, 0.0)

    out: Dict[str, float] = {}
    for iso, vals in totals.items():
        pop = vals["pop"]
        out[iso] = (vals["gdp"] / pop) if pop > 0 else 0.0
    return out


def _build_country_border_graph(land: gpd.GeoDataFrame) -> Dict[str, Set[str]]:
    by_country = (
        land[["country", "geometry"]]
        .dissolve(by="country", as_index=False)
        .reset_index(drop=True)
    )

    countries = [normalize_iso(v) for v in by_country["country"].tolist()]
    geoms = by_country.geometry.tolist()
    graph: Dict[str, Set[str]] = {iso: set() for iso in countries if iso}

    for i in range(len(geoms)):
        iso_i = countries[i]
        if not iso_i:
            continue

        geom_i = geoms[i]
        if geom_i is None or geom_i.is_empty:
            continue

        for j in range(i + 1, len(geoms)):
            iso_j = countries[j]
            if not iso_j:
                continue

            geom_j = geoms[j]
            if geom_j is None or geom_j.is_empty:
                continue

            if geom_i.touches(geom_j):
                graph[iso_i].add(iso_j)
                graph[iso_j].add(iso_i)

    return graph


def _load_manual_relationships(
    land: gpd.GeoDataFrame,
    target_year: int,
) -> Dict[Tuple[str, str], Dict[str, object]]:
    input_path = _resolve_input_path()
    if input_path is None:
        print(
            "[REL] country_relationships_totals.csv not found. "
            "Relationships will be generated from heuristic rules."
        )
        return {}

    rel_df = pd.read_csv(input_path, sep=";")
    if len(rel_df.columns) == 1:
        rel_df = pd.read_csv(input_path)

    country_a_col = next(
        (c for c in ["country_a", "iso3_a", "state_a", "country1"] if c in rel_df.columns),
        None,
    )
    country_b_col = next(
        (c for c in ["country_b", "iso3_b", "state_b", "country2"] if c in rel_df.columns),
        None,
    )
    score_col = next(
        (
            c
            for c in [
                "relationship_score",
                "score",
                "relations",
                "relation_value",
                "diplomatic_score",
            ]
            if c in rel_df.columns
        ),
        None,
    )
    year_col = next((c for c in ["year", "relationship_year"] if c in rel_df.columns), None)
    source_col = "source" if "source" in rel_df.columns else None

    if country_a_col is None or country_b_col is None or score_col is None:
        print("[REL] Input file missing required columns; manual relationship overrides disabled.")
        return {}

    land_isos = set(normalize_iso(v) for v in land["country"].dropna().unique())
    name_lookup = _build_name_to_iso_lookup(land)

    best_by_pair: Dict[Tuple[str, str], Dict[str, object]] = {}

    for _, row in rel_df.iterrows():
        iso_a = _parse_country_ref(row.get(country_a_col), name_lookup, land_isos)
        iso_b = _parse_country_ref(row.get(country_b_col), name_lookup, land_isos)
        if not iso_a or not iso_b or iso_a == iso_b:
            continue

        score = parse_number(row.get(score_col))
        if score is None:
            continue

        year_value: Optional[int] = None
        if year_col:
            year_numeric = pd.to_numeric(row.get(year_col), errors="coerce")
            if pd.notna(year_numeric):
                year_value = int(year_numeric)

        source_value = "manual_dataset"
        if source_col:
            src = str(row.get(source_col) or "").strip()
            if src:
                source_value = src

        key = tuple(sorted((iso_a, iso_b)))
        rec = {
            "score": clamp_score(score),
            "year": year_value,
            "source": source_value,
        }

        old = best_by_pair.get(key)
        if old is None:
            best_by_pair[key] = rec
            continue

        old_year = old.get("year")
        if old_year is None and year_value is not None:
            best_by_pair[key] = rec
            continue
        if year_value is not None and old_year is not None and year_value <= target_year and old_year <= target_year:
            if year_value > old_year:
                best_by_pair[key] = rec
            continue
        if year_value is not None and old_year is not None and old_year > target_year >= year_value:
            best_by_pair[key] = rec

    if best_by_pair:
        print(f"[REL] Loaded manual relationship overrides for {len(best_by_pair)} country pairs.")

    return best_by_pair


def _heuristic_score(
    iso_a: str,
    iso_b: str,
    border_graph: Dict[str, Set[str]],
    ideology_by_country: Dict[str, str],
    gdp_pc_by_country: Dict[str, float],
) -> Tuple[float, bool, bool, float]:
    is_border = iso_b in border_graph.get(iso_a, set())
    ideology_a = ideology_by_country.get(iso_a, "unknown")
    ideology_b = ideology_by_country.get(iso_b, "unknown")
    same_ideology = bool(
        ideology_a
        and ideology_b
        and ideology_a != "unknown"
        and ideology_b != "unknown"
        and ideology_a == ideology_b
    )

    score = 0.0
    score += 20.0 if is_border else -5.0

    if ideology_a == "unknown" or ideology_b == "unknown":
        score += 0.0
    elif same_ideology:
        score += 30.0
    else:
        score -= 25.0

    gdp_a = max(float(gdp_pc_by_country.get(iso_a, 0.0)), 0.0)
    gdp_b = max(float(gdp_pc_by_country.get(iso_b, 0.0)), 0.0)
    ratio = 0.0
    if gdp_a > 0 and gdp_b > 0:
        ratio = max(gdp_a, gdp_b) / min(gdp_a, gdp_b)
        if ratio >= 6.0:
            score -= 20.0
        elif ratio >= 3.0:
            score -= 10.0
        elif ratio <= 1.5:
            score += 5.0

    if not is_border and not same_ideology:
        score -= 10.0

    return clamp_score(score), is_border, same_ideology, ratio


def _build_country_relationship_index(
    countries: List[str],
    pair_rows: List[Dict[str, object]],
    border_graph: Dict[str, Set[str]],
) -> Dict[str, float]:
    score_lookup: Dict[Tuple[str, str], float] = {}
    for row in pair_rows:
        a = normalize_iso(row.get("country_a"))
        b = normalize_iso(row.get("country_b"))
        if not a or not b:
            continue
        key = tuple(sorted((a, b)))
        score_lookup[key] = float(row.get("relationship_score") or 0.0)

    out: Dict[str, float] = {}
    country_set = set(countries)

    for iso in countries:
        neighbors = sorted(border_graph.get(iso, set()) & country_set)
        peers = neighbors if neighbors else sorted(v for v in countries if v != iso)
        if not peers:
            out[iso] = 0.0
            continue

        vals = []
        for other in peers:
            key = tuple(sorted((iso, other)))
            vals.append(score_lookup.get(key, 0.0))

        out[iso] = clamp_score(sum(vals) / float(len(vals)))

    return out


def generate_relationship_dataset(
    land: gpd.GeoDataFrame,
    ideology_rows: Optional[List[Dict[str, object]]] = None,
    gdp_rows: Optional[List[Dict[str, object]]] = None,
    out_path: str = OUT_PATH,
    out_country_path: str = COUNTRY_OUT_PATH,
    template_path: str = TEMPLATE_OUT_PATH,
    write_csv: bool = True,
    target_year: int = TARGET_RELATIONSHIP_YEAR,
) -> Tuple[
    Dict[str, float],
    Dict[Tuple[str, str], float],
    List[Dict[str, object]],
]:
    countries = sorted(set(normalize_iso(v) for v in land["country"].dropna().unique() if normalize_iso(v)))

    border_graph = _build_country_border_graph(land)
    ideology_by_country = _build_country_ideology_lookup(ideology_rows)
    gdp_pc_by_country = _build_country_gdp_pc_lookup(gdp_rows)
    manual_pairs = _load_manual_relationships(land, target_year)

    pair_rows: List[Dict[str, object]] = []
    pair_lookup: Dict[Tuple[str, str], float] = {}

    for i, iso_a in enumerate(countries):
        for iso_b in countries[i + 1 :]:
            key = tuple(sorted((iso_a, iso_b)))
            manual = manual_pairs.get(key)

            if manual is not None:
                score = clamp_score(manual.get("score") or 0.0)
                is_border = iso_b in border_graph.get(iso_a, set())
                ideology_a = ideology_by_country.get(iso_a, "unknown")
                ideology_b = ideology_by_country.get(iso_b, "unknown")
                same_ideology = bool(
                    ideology_a
                    and ideology_b
                    and ideology_a != "unknown"
                    and ideology_b != "unknown"
                    and ideology_a == ideology_b
                )
                gdp_a = max(float(gdp_pc_by_country.get(iso_a, 0.0)), 0.0)
                gdp_b = max(float(gdp_pc_by_country.get(iso_b, 0.0)), 0.0)
                ratio = (max(gdp_a, gdp_b) / min(gdp_a, gdp_b)) if gdp_a > 0 and gdp_b > 0 else 0.0
                source = str(manual.get("source") or "manual_dataset")
                year = manual.get("year") or ""
            else:
                score, is_border, same_ideology, ratio = _heuristic_score(
                    iso_a,
                    iso_b,
                    border_graph,
                    ideology_by_country,
                    gdp_pc_by_country,
                )
                source = "heuristic_border_ideology_gdp"
                year = ""

            pair_lookup[key] = score
            pair_rows.append(
                {
                    "country_a": iso_a,
                    "country_b": iso_b,
                    "relationship_score": round(score, 2),
                    "is_border": int(is_border),
                    "same_ideology": int(same_ideology),
                    "gdp_pc_ratio": round(float(ratio), 6),
                    "relationship_source": source,
                    "relationship_year": year,
                }
            )

    country_index = _build_country_relationship_index(countries, pair_rows, border_graph)
    country_rows = [
        {
            "country_iso3": iso,
            "relationship_index": round(country_index.get(iso, 0.0), 2),
            "border_neighbor_count": int(len(border_graph.get(iso, set()))),
            "ideology": ideology_by_country.get(iso, "unknown"),
            "gdp_per_capita": round(float(gdp_pc_by_country.get(iso, 0.0)), 6),
        }
        for iso in countries
    ]

    if write_csv:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        pd.DataFrame(pair_rows).to_csv(out_path, sep=";", index=False)
        pd.DataFrame(country_rows).to_csv(out_country_path, sep=";", index=False)

        # Full matrix template for runtime usage in Godot.
        matrix: Dict[str, Dict[str, float]] = {
            iso: {peer: 0.0 for peer in countries}
            for iso in countries
        }
        for iso in countries:
            matrix[iso][iso] = 100.0

        for (iso_a, iso_b), score in pair_lookup.items():
            val = round(float(score), 2)
            matrix.setdefault(iso_a, {})[iso_b] = val
            matrix.setdefault(iso_b, {})[iso_a] = val

        payload = {
            "version": 1,
            "relationship_scale": {
                "min": -100,
                "max": 100,
                "self_default": 100,
            },
            "countries": countries,
            "matrix": matrix,
            "country_index": {
                iso: round(float(country_index.get(iso, 0.0)), 2)
                for iso in countries
            },
            "notes": [
                "Matrix contains score for every state-to-state pair.",
                "Diagonal self relation is fixed to 100.",
                "Pair scores are symmetric in this pipeline.",
            ],
        }

        with open(template_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=True, indent=2)

    return country_index, pair_lookup, pair_rows
