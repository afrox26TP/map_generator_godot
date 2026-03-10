import os
import re
from typing import Dict, List, Optional, Tuple

import geopandas as gpd
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
COUNTRY_GDP_PATH = os.path.join(BASE, "country_gdp_totals.csv")
OUT_DIR = os.path.join(BASE, "opengs_export")
OUT_PATH = os.path.join(OUT_DIR, "GDP.csv")
TARGET_GDP_YEAR = 2023


def normalize(text: str) -> str:
    if not isinstance(text, str):
        return ""
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return text.strip()


def normalize_iso(value: Optional[str]) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().upper().replace(" ", "")


def parse_number(value) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        num = float(value)
        return num if num > 0 else None

    txt = str(value).strip()
    if not txt:
        return None

    txt = txt.replace(" ", "").replace("_", "")
    txt = re.sub(r"[^0-9,.-]", "", txt)

    # Handle decimal comma inputs such as 1234,56.
    if "," in txt and "." in txt:
        if txt.rfind(",") > txt.rfind("."):
            # Example: 1.234,56 -> 1234.56
            txt = txt.replace(".", "").replace(",", ".")
        else:
            # Example: 1,234.56 -> 1234.56
            txt = txt.replace(",", "")
    elif "," in txt:
        txt = txt.replace(",", ".")

    num = pd.to_numeric(txt, errors="coerce")
    if pd.isna(num):
        return None

    out = float(num)
    return out if out > 0 else None


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


def load_country_gdp(land: gpd.GeoDataFrame, target_year: int) -> Dict[str, Dict[str, Optional[float]]]:
    if not os.path.exists(COUNTRY_GDP_PATH):
        print(
            "[GDP] country_gdp_totals.csv not found. "
            "GDP map will be empty until country GDP data is provided."
        )
        return {}

    gdp_df = pd.read_csv(COUNTRY_GDP_PATH, sep=";")
    if len(gdp_df.columns) == 1:
        gdp_df = pd.read_csv(COUNTRY_GDP_PATH)

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
            if c in gdp_df.columns
        ),
        None,
    )
    gdp_total_col = next(
        (c for c in ["gdp_total", "total_gdp", "gdp", "nominal_gdp", "gdp_usd"] if c in gdp_df.columns),
        None,
    )
    gdp_pc_col = next(
        (c for c in ["gdp_per_capita", "gdp_pc", "per_capita", "gdp_per_person"] if c in gdp_df.columns),
        None,
    )
    year_col = next((c for c in ["year", "gdp_year"] if c in gdp_df.columns), None)
    source_col = "source" if "source" in gdp_df.columns else None

    if country_col is None or (gdp_total_col is None and gdp_pc_col is None):
        raw_df = pd.read_csv(COUNTRY_GDP_PATH, sep=";", header=None)
        if raw_df.shape[1] >= 2 and _looks_like_iso3(raw_df.iloc[:, 0]):
            rename = {0: "country_iso3", 1: "gdp_total"}

            # Accept multiple headerless layouts:
            # 5 cols: ISO3;gdp_total;gdp_per_capita;year;source
            # 4 cols: ISO3;gdp_total;year;source (population-style) OR ISO3;gdp_total;gdp_pc;year
            # 3 cols: ISO3;gdp_total;year OR ISO3;gdp_total;gdp_pc
            ncols = raw_df.shape[1]
            if ncols >= 5:
                rename[2] = "gdp_per_capita"
                rename[3] = "year"
                rename[4] = "source"
            elif ncols == 4:
                if _looks_like_year_column(raw_df.iloc[:, 2]):
                    rename[2] = "year"
                    rename[3] = "source"
                else:
                    rename[2] = "gdp_per_capita"
                    rename[3] = "year"
            elif ncols == 3:
                if _looks_like_year_column(raw_df.iloc[:, 2]):
                    rename[2] = "year"
                else:
                    rename[2] = "gdp_per_capita"

            gdp_df = raw_df.rename(columns=rename)
            country_col = "country_iso3"
            gdp_total_col = "gdp_total"
            gdp_pc_col = "gdp_per_capita" if "gdp_per_capita" in gdp_df.columns else None
            year_col = "year" if "year" in gdp_df.columns else None
            source_col = "source" if "source" in gdp_df.columns else None
            print("[GDP] country_gdp_totals.csv loaded as headerless format.")
        else:
            print("[GDP] country_gdp_totals.csv missing required columns; ignoring GDP input.")
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
            admin_name = normalize(row.get("admin", ""))
            if iso:
                name_to_iso[normalize(iso)] = iso
                if admin_name:
                    name_to_iso[admin_name] = iso

    selected_rows = []
    for _, group in gdp_df.groupby(country_col):
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
    gdp_by_iso: Dict[str, Dict[str, Optional[float]]] = {}

    for _, row in selected_df.iterrows():
        raw_country = str(row.get(country_col, "")).strip()
        gdp_total = parse_number(row.get(gdp_total_col)) if gdp_total_col else None
        gdp_pc = parse_number(row.get(gdp_pc_col)) if gdp_pc_col else None
        source_value = str(row.get(source_col, "")).strip() if source_col else ""

        # Compatibility fallback for rows filled in population-style templates,
        # where the numeric GDP value may end up in the final source column.
        if gdp_total is None and gdp_pc is None and source_col:
            source_numeric = parse_number(source_value)
            if source_numeric is not None:
                gdp_total = source_numeric
                source_value = ""

        if gdp_total is None and gdp_pc is None:
            continue

        iso = None
        if re.fullmatch(r"[A-Za-z]{3}", raw_country):
            cand = raw_country.upper()
            if cand in land_isos:
                iso = cand

        if iso is None:
            iso = name_to_iso.get(normalize(raw_country))

        if iso is None:
            continue

        year_value: Optional[int] = None
        if year_col and year_col in row:
            year_numeric = pd.to_numeric(row.get(year_col), errors="coerce")
            if pd.notna(year_numeric):
                year_value = int(year_numeric)

        record = {
            "gdp_total": gdp_total,
            "gdp_per_capita": gdp_pc,
            "year": year_value,
            "source": source_value,
        }

        existing = gdp_by_iso.get(iso)
        if existing is None:
            gdp_by_iso[iso] = record
            continue

        # Prefer records that include a country total GDP value.
        existing_total = existing.get("gdp_total")
        if existing_total is None and gdp_total is not None:
            gdp_by_iso[iso] = record
            continue

        # Otherwise keep the record with the newer year where available.
        existing_year = existing.get("year") or -1
        record_year = year_value or -1
        if record_year > existing_year:
            gdp_by_iso[iso] = record

    if gdp_by_iso:
        print(f"[GDP] Loaded GDP inputs for {len(gdp_by_iso)} countries.")
    return gdp_by_iso


def _allocate_by_population(province_ids: List[int], population: Dict[int, float], country_total: float) -> Dict[int, float]:
    if not province_ids:
        return {}

    pop_sum = sum(max(population.get(pid, 0.0), 0.0) for pid in province_ids)
    if pop_sum <= 0:
        equal = country_total / float(len(province_ids))
        return {pid: equal for pid in province_ids}

    out: Dict[int, float] = {}
    for pid in province_ids:
        share = max(population.get(pid, 0.0), 0.0) / pop_sum
        out[pid] = country_total * share
    return out


def build_output_rows(
    land: gpd.GeoDataFrame,
    population: Dict[int, float],
    gdp_values: Dict[int, float],
    source_by_pid: Dict[int, str],
    year_by_pid: Dict[int, Optional[int]],
) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    for pid, prow in land.iterrows():
        pop = max(float(population.get(pid, 0.0)), 0.0)
        gdp_val = max(float(gdp_values.get(pid, 0.0)), 0.0)
        gdp_pc = (gdp_val / pop) if pop > 0 else 0.0
        rows.append(
            {
                "province_id": int(pid),
                "province_name": str(prow.get("name_en") or prow.get("name") or ""),
                "country_iso3": str(prow.get("country") or ""),
                "country_name": str(prow.get("admin") or prow.get("country") or ""),
                "population": int(round(pop)),
                "gdp": round(gdp_val, 2),
                "gdp_per_capita": round(gdp_pc, 6),
                "gdp_source": source_by_pid.get(pid, "missing_country_gdp"),
                "gdp_year": year_by_pid.get(pid) or "",
            }
        )
    return rows


def generate_gdp_dataset(
    land: gpd.GeoDataFrame,
    population: Dict[int, float],
    out_path: str = OUT_PATH,
    write_csv: bool = True,
    target_year: int = TARGET_GDP_YEAR,
) -> Tuple[Dict[int, float], List[Dict[str, object]], List[str]]:
    """
    Build province GDP values from country-level inputs.

    Rules:
    - If country total GDP is provided, split by province population share.
    - Else if GDP per capita is provided, multiply by province population.
    - Else province GDP remains 0 for that country.
    """
    country_gdp = load_country_gdp(land, target_year)

    country_to_pids: Dict[str, List[int]] = {}
    for pid, row in land.iterrows():
        iso3 = normalize_iso(str(row.get("country", "")))
        if not iso3:
            continue
        country_to_pids.setdefault(iso3, []).append(pid)

    gdp_values: Dict[int, float] = {}
    source_by_pid: Dict[int, str] = {}
    year_by_pid: Dict[int, Optional[int]] = {}
    missing_countries: List[str] = []

    for iso3, pids in country_to_pids.items():
        gdp_entry = country_gdp.get(iso3)
        if not gdp_entry:
            missing_countries.append(iso3)
            for pid in pids:
                gdp_values[pid] = 0.0
                source_by_pid[pid] = "missing_country_gdp"
                year_by_pid[pid] = None
            continue

        gdp_total = gdp_entry.get("gdp_total")
        gdp_pc = gdp_entry.get("gdp_per_capita")
        gdp_year = gdp_entry.get("year")

        if gdp_total is not None and gdp_total > 0:
            allocated = _allocate_by_population(pids, population, float(gdp_total))
            for pid, value in allocated.items():
                gdp_values[pid] = value
                source_by_pid[pid] = "country_total_population_share"
                year_by_pid[pid] = gdp_year
            continue

        if gdp_pc is not None and gdp_pc > 0:
            for pid in pids:
                pop = max(float(population.get(pid, 0.0)), 0.0)
                gdp_values[pid] = float(gdp_pc) * pop
                source_by_pid[pid] = "gdp_per_capita_population"
                year_by_pid[pid] = gdp_year
            continue

        missing_countries.append(iso3)
        for pid in pids:
            gdp_values[pid] = 0.0
            source_by_pid[pid] = "missing_country_gdp"
            year_by_pid[pid] = gdp_year

    rows = build_output_rows(land, population, gdp_values, source_by_pid, year_by_pid)

    if write_csv:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        pd.DataFrame(rows).to_csv(out_path, sep=";", index=False)

    if missing_countries:
        print(
            f"[GDP] Missing country GDP input for {len(missing_countries)} countries "
            "(GDP kept at 0 for those countries)."
        )

    return gdp_values, rows, missing_countries


def main():
    print("Run this module from export_to_opengs.py where land + population are available.")


if __name__ == "__main__":
    main()