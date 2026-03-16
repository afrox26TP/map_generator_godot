# Documentation for `map_generator_godot` 

## 0. What this is, super simply
This project is basically a map generator for a Godot strategy game.

You feed it:
- geographic data (province shapes),
- tables with population, GDP, and ideology.

It outputs:
- image maps (`.png`),
- data tables (`.txt`, `.csv`, `.json`),

so the game can load everything directly.

One sentence for defense:
"I turn open geodata and statistics into complete runtime map assets for a strategy game."

## 1. What the project does exactly
Main things this project does:

1. Loads European admin regions from Natural Earth.
2. Cleans geometry (fixes, Europe clipping, tiny region merges).
3. Generates sea provinces too (using Voronoi + KMeans).
4. Draws maps (`ProvinceMap`, `PoliticalMap`, thematic maps).
5. Fills provinces with stats (population, GDP, ideology).
6. Exports everything into formats the game can read.

## 2. Where things are (file overview)
Main code folder: `build_map/src`.

- `build_map.py`
  - the main pipeline, from data loading to final export.
- `export_to_opengs.py`
  - most important export file (images + txt/csv/json).
- `export_shared.py`
  - shared constants and helpers (mainly geometry-to-pixel conversion).
- `export_political_map.py`
  - draws the political map.
- `export_theme_map.py`
  - draws GDP/Population/Ideology maps + builds `Modes/*` folders.
- `import_population.py`
  - matches and computes province-level population.
- `import_gdp.py`
  - computes province-level GDP from country inputs.
- `import_ideology.py`
  - maps country-level ideology to provinces.
- `wdqs_batches.py`
  - prepares SPARQL batch queries for Wikidata.

Helper `.bat` scripts:
- `install.bat` = creates a venv + installs dependencies.
- `run.bat` = runs `python build_map.py`.
- `deploy.bat` = packs current content into a ZIP.

## 3. What you need prepared
### 3.1 Python and libraries
Recommended Python version: `3.12.7`.

Dependencies (`requirements.txt`):
- geopandas
- shapely
- pyproj
- rtree
- numpy
- pandas
- matplotlib
- scikit-learn
- pillow

### 3.2 Input data
Required:
- `ne_10m_admin_1_states_provinces.shp` (+ `.dbf`, `.shx`, `.prj`, etc.)

Important data inputs:
- `query.csv` (population from WDQS or compatible format)
- `country_gdp_totals.csv`
- `country_ideology_totals.csv` or `country_ideology_totals_starter.csv`

Optional (but very useful):
- `country_population_totals.csv`
- `province_population_seed.csv`
- `population_aliases_starter.csv`

## 4. How to run it
From `build_map/src`:

```bat
install.bat
run.bat
```

Or manually:

```powershell
python -m venv venv
.\venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt
python build_map.py
```

After it finishes, outputs are in `build_map/src/opengs_export`.

## 5. What you should see in logs (so you know it is healthy)
Typical flow:
- `PART 1 START` -> loading + Europe filtering.
- `Capital provinces tagged` -> capital tagging in provinces.
- `PART 2.5 START` -> tiny province merging.
- `PART 3 START` -> sea region generation.
- `Sea regions generated` -> how many sea regions were created.
- `[EXPORT] ProvinceMap...`
- `[EXPORT] Population CSV + map colors...`
- `[EXPORT] GDP CSV + map colors...`
- `[EXPORT] Ideology CSV + map colors...`
- `[EXPORT] EXPORT COMPLETE`

If you see `EXPORT COMPLETE`, the pipeline finished end-to-end.

## 6. How `build_map.py` works (step by step)

### 6.1 Load and filter Europe
What happens:
1. Load Natural Earth shapefile.
2. Reproject data to `EPSG:3035`.
3. Fix geometry with `buffer(0)`.
4. Keep only countries from `EUROPE_COUNTRIES`.
5. Clip Russia to European part (`cut_russia`).
6. Clip everything again to the Europe bounding box.

Important for defense:
- `EPSG:3035` is metric CRS, so area and distance logic is reliable.

### 6.2 Tag capital provinces
`mark_capital_provinces` does this:
- first checks if region type is explicitly `capital`,
- if missing, uses fallback points from `COUNTRY_CAPITAL_POINTS` (lon/lat),
- transforms point to map CRS and picks the best province.

It creates columns:
- `is_capital_province` (0/1)
- `capital_city_name`

### 6.3 Geometry cleaning
- removes interior holes (`remove_holes`),
- applies topology fix again (`buffer(0)`),
- builds `land_union` (merged land area).

### 6.4 Merge tiny provinces
`merge_small_absolute`:
- processes per country,
- if province area is below `MIN_AREA_ABS = 1_000_000_000`,
- merges it into nearest province of the same country.

Important:
- capital info is preserved through merges (`is_capital_province`, `capital_city_name`).

### 6.5 Sea region generation
Process:
1. Build a bounding box around land.
2. Subtract land -> remaining area is sea.
3. Generate up to 15000 random points in sea.
4. Cluster points with `KMeans` into `N_REGIONS = 60` centers.
5. Compute Voronoi diagram from centers.
6. Clip Voronoi cells to sea and smooth with `buffer(+15000).buffer(-15000)`.

Result: `final_regions` = sea provinces.

### 6.6 Preview
Creates `preview_map.png` for quick visual sanity check.

### 6.7 Hand-off to export
At the end:

```python
run_export(land, final_regions)
```

This enters the main export stage.

## 7. What `export_to_opengs.py` does

### 7.1 `export_province_map`
Creates `ProvinceMap.png` (4096x4096):
- each land province gets unique RGB,
- each sea region also gets unique RGB.

Returns:
- `province_colors` (color -> `pid` map),
- `bounds` (for coordinate conversions).

### 7.2 `export_id_map`
This is a key technical piece.

What it does:
- loads `ProvinceMap.png`,
- builds LUT `256x256x256` for RGB -> ID mapping,
- assigns stable sea IDs (`max_pid + 1`, `+2`, ...),
- writes `ProvinceIDMask.png` (and alias `ProvinceMask.png`).

ID encoding into RGB:
- `R = id & 0xFF`
- `G = (id >> 8) & 0xFF`
- `B = (id >> 16) & 0xFF`

Safety:
- if ID > `16777215` (`0xFFFFFF`), export fails with a clear error.

### 7.3 `export_political_map`
- each country gets a random color,
- provinces are colored by country,
- sea remains `SEA_COLOR`.

Result: `PoliticalMap.png`.

### 7.4 `export_provinces_txt`
Generates main runtime table `Provinces.txt`.

Header:

`id;R;G;B;type;state;owner;controller;x;y;province_name;country_name;population;gdp;gdp_per_capita;is_capital;capital_city;neighbors;ideology`

How fields are filled:
- `type` is `land` or `sea`,
- `x,y` is province centroid in pixels (sea uses `0,0`),
- `population/gdp/ideology` comes from import modules,
- `neighbors` are computed from pixel borders in ID map.

### 7.5 How `neighbors` are computed
Algorithm over ID matrix:
1. Compare horizontally adjacent pixels.
2. Compare vertically adjacent pixels.
3. Where IDs differ, there is a border between two provinces.
4. Deduplicate pairs and store them bidirectionally.

Why this is good:
- it is fast,
- it matches the exact raster used by the runtime.

### 7.6 Other exports
- `Population.txt`
- `GDP.txt`
- `Ideology.txt`
- `ProvincePopulationLookup.json`
- `States.txt`
- `States/*.txt`

## 8. Thematic maps (`export_theme_map.py`)

### 8.1 General principle
`export_theme_map`:
- iterates pixel-by-pixel,
- uses `id_map` to fetch province color value,
- paints sea with constant `SEA_COLOR`,
- redraws sea outlines,
- saves final PNG.

### 8.2 GDP map
`export_gdp_map`:
- if GDP data exists, uses logarithmic scale (`log10`),
- gradient from light sand to dark red,
- falls back to default/random styling if data is missing.

### 8.3 Population map
`export_population_map`:
- ideally uses density (`population / km2`),
- uses global log scale,
- for imputed data mixes global/local contrast,
- green gradient from light to dark.

### 8.4 Ideology map
`export_ideology_map`:
- canonical labels: `demokracie`, `kralovstvi`, `autokracie`, `unknown`.

Fixed colors:
- demokracie = blue
- kralovstvi = gold
- autokracie = red
- unknown = gray

### 8.5 `Modes/*` folders
`export_mode_folder`:
- moves map into `Modes/<Mode>/`,
- creates `manifest.txt` and `meta.json`,
- if destination PNG is locked, writes timestamp fallback file.

## 9. Population module (`import_population.py`) in plain terms

### 9.1 Why this part is hard
Real population datasets are messy:
- different region names,
- mixed languages,
- different admin levels,
- old observations,
- missing `iso` values.

So this module is intentionally robust.

### 9.2 Match priority
Matching priority:
1. `iso`
2. `exact_country`
3. `region_only`
4. `fuzzy_contain`
5. `fuzzy_best`

If there is a conflict, it keeps better priority or newer date.

### 9.3 Consistent distribution
`USE_CONSISTENT_DISTRIBUTION = True`.

This means:
- keeps existing matched provinces,
- imputes missing ones,
- can calibrate to official country totals,
- uses special region-guided strategy for `FRA/ESP/GBR`.

### 9.4 Important constants
- `TARGET_POP_YEAR = 2023`
- `MIN_POP_YEAR = 2000`
- `FORCE_SEED_ONLY_COUNTRIES = {"FRA", "ESP", "GBR"}`
- `FORCE_WEIGHT_EXPONENT = 0.85`

## 10. GDP module (`import_gdp.py`) in plain terms
Rules per country:

1. If `gdp_total` exists -> split across provinces by population share.
2. If `gdp_total` is missing but `gdp_per_capita` exists -> `gdp = gdp_per_capita * population`.
3. If both missing -> `gdp = 0`.

Parser is robust:
- handles decimal comma formats,
- supports both header and headerless CSV.

## 11. Ideology module (`import_ideology.py`) in plain terms
- reads country ideology and propagates it to provinces.
- maps synonyms into canonical labels.

Canonical outputs:
- `demokracie`
- `kralovstvi`
- `autokracie`
- `unknown`

## 12. What you will find in outputs (`opengs_export`)
Typical set:
- `ProvinceMap.png`
- `ProvinceIDMask.png`
- `ProvinceMask.png`
- `PoliticalMap.png`
- `Population.csv`
- `Population.txt`
- `GDP.csv`
- `GDP.txt`
- `Ideology.csv`
- `Ideology.txt`
- `Provinces.txt`
- `States.txt`
- `ProvincePopulationLookup.json`
- `States/*.txt`
- `Modes/GDP/*`
- `Modes/Population/*`
- `Modes/Ideology/*`

## 13. Important data formats

### 13.1 `Provinces.txt`
Columns:
- `id`
- `R;G;B`
- `type`
- `state`
- `owner`
- `controller`
- `x;y`
- `province_name`
- `country_name`
- `population`
- `gdp`
- `gdp_per_capita`
- `is_capital`
- `capital_city`
- `neighbors`
- `ideology`

### 13.2 `States.txt`
Each row:

`ISO3;R;G;B`

### 13.3 `Population.txt`
`id;population;population_source;population_date;source_region;source_country;match_method`

### 13.4 `GDP.txt`
`id;gdp;gdp_per_capita;gdp_source;gdp_year`

### 13.5 `Ideology.txt`
`id;ideology;ideology_source;ideology_year`

## 14. One province from start to runtime
To make the full flow clear for one piece of map:

1. Comes from the shapefile.
2. Passes Europe filtering.
3. Geometry is cleaned.
4. May be merged if too small.
5. Gets unique color in `ProvinceMap`.
6. Gets numeric ID in `ProvinceIDMask`.
7. Gets population (match or imputation).
8. Gets GDP.
9. Gets ideology.
10. Gets neighbor list.
11. Is written as a row in `Provinces.txt`.
12. The game loads and uses it.

## 15. Most common problems and fixes

### 15.1 `country_gdp_totals.csv not found`
What it means:
- GDP input is missing.

What to do:
1. Add `country_gdp_totals.csv` into `build_map/src`.
2. Verify columns (`country_iso3` + `gdp_total` or `gdp_per_capita`).
3. Run again.

### 15.2 Too many `unmatched` in population
What it means:
- regions from `query.csv` matched poorly.

What to do:
1. Check `regionLabel`/`countryLabel` naming.
2. Add aliases in `population_aliases_starter.csv`.
3. Add `iso` where possible.
4. Compare `Population_debug.csv` before/after.

### 15.3 `PermissionError` while writing PNG
What it means:
- file is locked by another app.

What to do:
1. Close image preview/viewer.
2. Run export again.
3. `Modes/*` has fallback naming, but removing lock is best.

### 15.4 Map looks empty
What it means:
- shapefile input or clipping issue.

What to do:
1. Verify all shapefile parts (`.shp/.dbf/.shx/.prj`).
2. Verify files are not corrupted.
3. Check `PART 1` and `PART 2` logs.

### 15.5 Broken text characters
What it means:
- wrong text encoding during open/write.

What to do:
1. Open files as UTF-8.
2. Do not overwrite exports in ANSI.

## 16. Fast post-run check (60 seconds)
1. `ProvinceMap.png` and `ProvinceIDMask.png` exist.
2. `Provinces.txt` contains both `land` and `sea` rows.
3. At least one province has `is_capital=1`.
4. `Population.csv` is not empty.
5. `GDP.csv` is not all zeros.
6. Each `Modes/*` folder has `manifest.txt` and `meta.json`.

## 17. Why it is designed this way (defense)
Most common arguments:

1. Projection in `EPSG:3035`
- needed for metric area and distance operations.

2. Russia clipping
- without it, Europe map extent is not balanced.

3. Tiny province merge
- gives more stable raster and more playable map.

4. Voronoi sea
- automatic sea region generation without manual drawing.

5. 24-bit ID mask
- fast and exact runtime lookup pixel -> province ID.

6. Robust population matching
- real-world source data is messy, so fallbacks are required.

## 18. Mini spoken script (3-5 minutes)
If you want a clean oral explanation:

1. "First, I load Europe admin map data and convert it to metric projection."
2. "Then I clean geometry, clip to Europe, and merge tiny regions."
3. "For sea, I generate regions automatically using KMeans + Voronoi."
4. "Then I build map layers: ProvinceMap, ID mask, and political map."
5. "On top of that I compute province-level population, GDP, and ideology."
6. "Finally I export runtime tables (`Provinces`, `States`) and thematic maps into `Modes` folders."
7. "The whole pipeline has fallbacks, so even incomplete data still gives consistent outputs."

## 19. Cheat line if interrupted
"The project converts geodata and statistics into complete game-ready map assets (PNG + TXT/CSV/JSON), including robust matching and fallbacks for imperfect data."

## 20. Full-flow pseudocode
```text
load_admin_shapes()
filter_to_europe()
cut_russia_to_europe()
clip_to_bbox()
mark_capitals()

clean_geometries()
merge_small_provinces()

sea_regions = build_voronoi_sea_regions()

province_colors = export_province_map(land, sea_regions)
id_map, sea_ids = export_id_map(province_colors)
export_political_map(id_map)

population = generate_population_dataset(land)
gdp = generate_gdp_dataset(land, population)
ideology = generate_ideology_dataset(land)

export_provinces_txt(id_map, land, population, gdp, ideology, sea_ids)
export_theme_maps(id_map, population, gdp, ideology)
export_states_files(land)
```

---
This documentation is based on the current implementation in `build_map/src` as of 2026-03-16.
Ai was used for Formulate words only.