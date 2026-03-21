# opengs-europe-map-tools
A simple pipeline for generating European province maps for Godot (OpenGS) or other grand strategy projects.
run on python 3.12.7 version

europe temp req data unzip and add to the root:

https://gisco-services.ec.europa.eu/distribution/v2/nuts/download/ref-nuts-2021-10m.geojson.zip

https://www.naturalearthdata.com/http//www.naturalearthdata.com/download/10m/cultural/ne_10m_admin_1_states_provinces.zip

## Country GDP input (for province GDP map)

To generate a real GDP map per province, add `build_map/src/country_gdp_totals.csv`.

You can start from `build_map/src/country_gdp_totals_starter.csv`.

Supported columns:

- `country_iso3` (preferred), or `iso3`, or `country`
- `gdp_total` (country total GDP)
- `gdp_per_capita` (GDP per person)
- `year` (optional)
- `source` (optional)

Rules used by the exporter:

- If `gdp_total` exists for a country, it is split across provinces by province population share.
- Else, if `gdp_per_capita` exists, province GDP = `gdp_per_capita * province_population`.
- If neither exists, province GDP is set to `0` for that country.

New outputs in `build_map/src/opengs_export/`:

- `GDP.csv` (province GDP dataset)
- `GDP.txt` (runtime-friendly GDP table)
- `GDPMap.png` (thematic map using computed GDP values)
- `Provinces.txt` now appends province runtime fields after the original columns: `province_name`, `country_name`, `population`, `gdp`, `gdp_per_capita`, `is_capital`, `capital_city`, `neighbors`, `ideology`, `recruitable_population`

## Country flags download (ISO3-compatible)

To download one flag per country using the same ISO3 codes used by this project (`CZE`, `DEU`, etc.), run:

```bash
cd build_map/src
python import_flags.py
```

Output:

- `build_map/src/opengs_export/Flags/ISO3.ext` (for example `CZE.svg`, `DEU.svg`)
- `build_map/src/opengs_export/country_flags.csv` (manifest with file name, source URL, status)

Notes:

- If `opengs_export/States.txt` exists, the script uses country codes from that file.
- Otherwise it falls back to `EUROPE_COUNTRIES` from `build_map.py`.
- You can force re-download with `python import_flags.py --force`.

## Ideology alternative flags (all states)

To generate ideology-specific variants for all target countries/states, run:

```bash
cd build_map/src
python import_flags.py --ideology-variants
```

Default ideology variants:

- `demokracie`
- `autokracie`
- `kralovstvi`
- `fasismus`
- `nacismus`

Output:

- `build_map/src/opengs_export/FlagsIdeology/ISO3__ideology.ext`
- `build_map/src/opengs_export/country_flags_ideology.csv`

## Army icons (all states)

To generate one army icon per country ISO3 code, run:

```bash
cd build_map/src
python generate_army_icons.py
```

Output:

- `build_map/src/opengs_export/ArmyIcons/ISO3.svg`
- `build_map/src/opengs_export/country_army_icons.csv`
- `build_map/src/opengs_export/ArmyIcons/ArmyIconTemplate.svg` (single colorable template for Godot)

Notes:

- If `opengs_export/States.txt` exists, the script uses country codes from that file.
- Otherwise it falls back to `EUROPE_COUNTRIES` from `build_map.py`.
- You can force regeneration with `python generate_army_icons.py --force`.
- In Godot, use `ArmyIconTemplate.svg` and set `modulate`/`self_modulate` to change icon color at runtime.
- To generate only the template file, run: `python generate_army_icons.py --template-only`.
- To generate ideology templates, run: `python generate_army_icons.py --template-only --ideology-templates`.
- Ideology templates are written to `build_map/src/opengs_export/ArmyIconsIdeologyTemplates/ArmyIconTemplate__ideology.svg`.
- To generate value-based ideology templates, run: `python generate_army_icons.py --template-only --ideology-templates --ideology-value-templates --ideology-values "20,50,80"`.
- Value templates are written as `ArmyIconTemplate__ideology__vXXX.svg` (for example `ArmyIconTemplate__demokracie__v080.svg`).

Behavior:

- Every `ISO3 + ideology` combination is generated for full coverage.
- If no historical ideology override exists, the script falls back to the base country flag.
- Included historical overrides: `DEU` (`autokracie`, `nacismus`), `ITA` (`autokracie`, `fasismus`, `kralovstvi`), `CZE` (`kralovstvi`).

Optional custom list:

```bash
python import_flags.py --ideology-variants --ideologies "demokracie autokracie kralovstvi fasismus nacismus"
```
