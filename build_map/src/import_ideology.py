import os
import re
import unicodedata
from typing import Dict, List, Optional, Tuple

import geopandas as gpd
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
COUNTRY_IDEOLOGY_PATH = os.path.join(BASE, "country_ideology_totals.csv")
COUNTRY_IDEOLOGY_STARTER_PATH = os.path.join(BASE, "country_ideology_totals_starter.csv")
OUT_DIR = os.path.join(BASE, "opengs_export")
OUT_PATH = os.path.join(OUT_DIR, "Ideology.csv")
TARGET_IDEOLOGY_YEAR = 2024


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


def _looks_like_iso3(series: pd.Series) -> bool:
    sample = series.dropna().astype(str).str.strip().head(20)
    if sample.empty:
        return False
    ratio = sample.str.fullmatch(r"[A-Za-z]{3}").mean()
    return bool(ratio >= 0.8)


def _looks_like_year_column(series: pd.Series) -> bool:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return False
    year_like_ratio = ((values >= 1900) & (values <= 2100)).mean()
    return bool(year_like_ratio >= 0.6)


def canonical_ideology(value: Optional[str]) -> str:
    norm = normalize_text(value)
    if not norm:
        return "unknown"

    alias_map = {
        "demokracie": "demokracie",
        "democracy": "demokracie",
        "democratic": "demokracie",
        "autokracie": "autokracie",
        "autocracy": "autokracie",
        "autocratic": "autokracie",
        "dictatorship": "autokracie",
        "kralovstvi": "kralovstvi",
        "kralostvi": "kralovstvi",
        "monarchy": "kralovstvi",
        "kingdom": "kralovstvi",
        "constitutional monarchy": "kralovstvi",
    }

    if norm in alias_map:
        return alias_map[norm]

    for token in norm.split():
        if token in alias_map:
            return alias_map[token]

    if "democr" in norm or "demokra" in norm:
        return "demokracie"
    if "autocr" in norm or "diktat" in norm or "dictat" in norm:
        return "autokracie"
    if "kralov" in norm or "kralost" in norm or "monarch" in norm or "kingdom" in norm:
        return "kralovstvi"

    return norm.replace(" ", "_")


def _resolve_input_path() -> Optional[str]:
    for path in (COUNTRY_IDEOLOGY_PATH, COUNTRY_IDEOLOGY_STARTER_PATH):
        if os.path.exists(path):
            return path
    return None


def load_country_ideology(
    land: gpd.GeoDataFrame,
    target_year: int,
) -> Dict[str, Dict[str, object]]:
    input_path = _resolve_input_path()
    if input_path is None:
        print(
            "[IDEOLOGY] country_ideology_totals.csv not found. "
            "Ideology map will use unknown colors until data is provided."
        )
        return {}

    ideology_df = pd.read_csv(input_path, sep=";")
    if len(ideology_df.columns) == 1:
        ideology_df = pd.read_csv(input_path)

    country_col = next(
        (
            c
            for c in [
                "country_iso3",
                "iso3",
                "country",
                "country_code",
                "country_or_iso3",
            ]
            if c in ideology_df.columns
        ),
        None,
    )
    ideology_col = next(
        (c for c in ["ideology", "government", "regime", "system", "type"] if c in ideology_df.columns),
        None,
    )
    year_col = next((c for c in ["year", "ideology_year"] if c in ideology_df.columns), None)
    source_col = "source" if "source" in ideology_df.columns else None

    if country_col is None or ideology_col is None:
        raw_df = pd.read_csv(input_path, sep=";", header=None)
        if raw_df.shape[1] >= 2 and _looks_like_iso3(raw_df.iloc[:, 0]):
            rename = {0: "country_iso3", 1: "ideology"}

            for idx in range(2, raw_df.shape[1]):
                if _looks_like_year_column(raw_df.iloc[:, idx]):
                    rename[idx] = "year"
                    break

            ideology_df = raw_df.rename(columns=rename)
            country_col = "country_iso3"
            ideology_col = "ideology"
            year_col = "year" if "year" in ideology_df.columns else None
            source_col = None
            print("[IDEOLOGY] country_ideology_totals.csv loaded as headerless format.")
        else:
            print("[IDEOLOGY] country_ideology_totals.csv missing required columns; ignoring ideology input.")
            return {}

    land_isos = (
        set(str(v).upper() for v in land["country"].dropna().unique())
        if "country" in land.columns
        else set()
    )
    name_to_iso: Dict[str, str] = {}
    if "country" in land.columns:
        for _, row in land[["country", "admin"]].drop_duplicates().iterrows():
            iso = normalize_iso(row.get("country", ""))
            admin_name = normalize_text(row.get("admin", ""))
            if iso:
                name_to_iso[normalize_text(iso)] = iso
                if admin_name:
                    name_to_iso[admin_name] = iso

    selected_rows = []
    for _, group in ideology_df.groupby(country_col):
        grp = group.copy()
        if year_col and year_col in grp.columns:
            grp[year_col] = pd.to_numeric(grp[year_col], errors="coerce")
            dated = grp[pd.notna(grp[year_col])]
            if dated.empty:
                pick = grp.iloc[-1]
            else:
                at_or_before = dated[dated[year_col] <= target_year]
                pick = (at_or_before if not at_or_before.empty else dated).sort_values(year_col).iloc[-1]
        else:
            pick = grp.iloc[-1]
        selected_rows.append(pick)

    selected_df = pd.DataFrame(selected_rows)
    ideology_by_iso: Dict[str, Dict[str, object]] = {}

    for _, row in selected_df.iterrows():
        raw_country = str(row.get(country_col, "")).strip()
        raw_ideology = str(row.get(ideology_col, "")).strip()
        if not raw_ideology:
            continue

        iso = None
        if re.fullmatch(r"[A-Za-z]{3}", raw_country):
            cand = raw_country.upper()
            if cand in land_isos:
                iso = cand

        if iso is None:
            iso = name_to_iso.get(normalize_text(raw_country))

        if iso is None:
            continue

        year_value: Optional[int] = None
        if year_col and year_col in row:
            year_numeric = pd.to_numeric(row.get(year_col), errors="coerce")
            if pd.notna(year_numeric):
                year_value = int(year_numeric)

        source_value = "manual_dataset"
        if source_col:
            source_raw = str(row.get(source_col, "")).strip()
            if source_raw:
                source_value = source_raw

        ideology_by_iso[iso] = {
            "ideology": canonical_ideology(raw_ideology),
            "ideology_raw": raw_ideology,
            "year": year_value,
            "source": source_value,
        }

    if ideology_by_iso:
        print(f"[IDEOLOGY] Loaded ideology inputs for {len(ideology_by_iso)} countries.")
    return ideology_by_iso


def generate_ideology_dataset(
    land: gpd.GeoDataFrame,
    out_path: str = OUT_PATH,
    write_csv: bool = True,
    target_year: int = TARGET_IDEOLOGY_YEAR,
) -> Tuple[Dict[int, str], List[Dict[str, object]], List[str]]:
    country_ideology = load_country_ideology(land, target_year)

    ideology_by_pid: Dict[int, str] = {}
    rows: List[Dict[str, object]] = []

    for pid, row in land.iterrows():
        iso3 = normalize_iso(str(row.get("country", "")))
        country_name = str(row.get("admin") or iso3)

        country_entry = country_ideology.get(iso3)
        if country_entry:
            ideology = str(country_entry.get("ideology") or "unknown")
            ideology_raw = str(country_entry.get("ideology_raw") or ideology)
            ideology_source = str(country_entry.get("source") or "manual_dataset")
            ideology_year = country_entry.get("year") or ""
        else:
            ideology = "unknown"
            ideology_raw = ""
            ideology_source = "missing_country_ideology"
            ideology_year = ""

        ideology_by_pid[int(pid)] = ideology
        rows.append(
            {
                "province_id": int(pid),
                "province_name": str(row.get("name_en") or row.get("name") or ""),
                "country_iso3": iso3,
                "country_name": country_name,
                "ideology": ideology,
                "ideology_raw": ideology_raw,
                "ideology_source": ideology_source,
                "ideology_year": ideology_year,
            }
        )

    missing = sorted(
        iso
        for iso in set(normalize_iso(str(v)) for v in land.get("country", []).tolist())
        if iso and iso not in country_ideology
    )

    if write_csv:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        pd.DataFrame(rows).to_csv(out_path, sep=";", index=False)

    return ideology_by_pid, rows, missing
