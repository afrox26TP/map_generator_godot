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
- `Provinces.txt` now appends province runtime fields after the original columns: `province_name`, `country_name`, `population`, `gdp`, `gdp_per_capita`
