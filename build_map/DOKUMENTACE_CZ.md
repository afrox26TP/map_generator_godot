# Dokumentace projektu `map_generator_godot` (studentska verze)

## 0. Co to je uplne jednoduse
Tenhle projekt je v praxi "generator mapy" pro hru v Godotu.

Do skriptu das:
- geograficka data (tvary provincii),
- tabulky s populaci, HDP a ideologii.

A skript vyrobi:
- obrazkove mapy (`.png`),
- datove tabulky (`.txt`, `.csv`, `.json`),

tak, aby to slo rovnou nacist ve hre.

Jedna veta na obhajobu:
"Z otevrenych geodat a statistik stavim kompletni runtime mapove podklady pro strategickou hru."

## 1. Co presne projekt dela
Hlavni veci, ktere projekt dela:

1. Nacte evropske admin regiony z Natural Earth.
2. Geometrii vycisti (opravy, orez mimo Evropu, slucovani mini regionu).
3. Vygeneruje i morske provincie (pomoci Voronoi + KMeans).
4. Nakresli mapy (`ProvinceMap`, `PoliticalMap`, tematicke mapy).
5. Naplni provincie statistikami (populace, HDP, ideologie).
6. Vyexportuje vse do formatu, co hra umi cist.

## 2. Co kde je (prehled souboru)
Adresar s kodem: `build_map/src`.

- `build_map.py`
  - hlavni pipeline, od nacitani dat az po final export.
- `export_to_opengs.py`
  - nejdulezitejsi exportni soubor (obrazky + txt/csv/json).
- `export_shared.py`
  - sdilene konstanty a funkce (hlavne prevod geometrie do pixelu).
- `export_political_map.py`
  - kresli mapu statu.
- `export_theme_map.py`
  - kresli mapy GDP/Population/Ideology + sklada slozky `Modes/*`.
- `import_population.py`
  - matchuje a dopoctava populaci po provinciich.
- `import_gdp.py`
  - pocita HDP po provinciich z country vstupu.
- `import_ideology.py`
  - mapuje ideologii z country levelu na provincie.
- `wdqs_batches.py`
  - pripravuje SPARQL batch dotazy na Wikidata.

Pomocne `.bat` skripty:
- `install.bat` = vytvori venv + nainstaluje zavislosti.
- `run.bat` = spusti `python build_map.py`.
- `deploy.bat` = zabali aktualni obsah do ZIPu.

## 3. Co musis mit pripraveno
### 3.1 Python a knihovny
Doporucena verze Pythonu: `3.12.7`.

Zavislosti (`requirements.txt`):
- geopandas
- shapely
- pyproj
- rtree
- numpy
- pandas
- matplotlib
- scikit-learn
- pillow

### 3.2 Vstupni data
Povinne:
- `ne_10m_admin_1_states_provinces.shp` (+ `.dbf`, `.shx`, `.prj` atd.)

Dulezite datove vstupy:
- `query.csv` (populace z WDQS nebo kompatibilni format)
- `country_gdp_totals.csv`
- `country_ideology_totals.csv` nebo `country_ideology_totals_starter.csv`

Volitelne (ale hodne uzitecne):
- `country_population_totals.csv`
- `province_population_seed.csv`
- `population_aliases_starter.csv`

## 4. Jak to spustit
Z adresare `build_map/src`:

```bat
install.bat
run.bat
```

Nebo rucne:

```powershell
python -m venv venv
.\venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt
python build_map.py
```

Po dobehnuti hledej vystupy v `build_map/src/opengs_export`.

## 5. Co uvidis v logu (at vis, ze to bezi dobre)
Typicky prubeh:
- `PART 1 START` -> nacitani + filtr Evropy.
- `Capital provinces tagged` -> oznaceni hlavniho mesta v provinciich.
- `PART 2.5 START` -> slucovani malych provincii.
- `PART 3 START` -> tvorba morskych regionu.
- `Sea regions generated` -> kolik morskych regionu vzniklo.
- `[EXPORT] ProvinceMap...`
- `[EXPORT] Population CSV + map colors...`
- `[EXPORT] GDP CSV + map colors...`
- `[EXPORT] Ideology CSV + map colors...`
- `[EXPORT] EXPORT COMPLETE`

Jestli vidis `EXPORT COMPLETE`, pipeline probehla do konce.

## 6. Jak funguje pipeline v `build_map.py` (krok po kroku)

### 6.1 Nacteni a filtr Evropy
Co se stane:
1. Nacte se Natural Earth shapefile.
2. Data se prehodi do `EPSG:3035`.
3. Geometrie se opravi pres `buffer(0)`.
4. Nechaji se jen staty ze seznamu `EUROPE_COUNTRIES`.
5. Rusko se oreze jen na evropskou cast (`cut_russia`).
6. Cele se to jeste oreze na mapovy bbox Evropy.

Pro obhajobu dulezite:
- `EPSG:3035` je metricky CRS, takze dava smysl pro plochy a vzdalenosti.

### 6.2 Oznaceni hlavniho mesta provincie
Funkce `mark_capital_provinces`:
- nejdriv hleda v datech, jestli je region explicitne `capital`,
- kdyz to chybi, pouzije fallback body `COUNTRY_CAPITAL_POINTS` (lon/lat),
- bod transformuje do CRS mapy a najde nejblizsi vhodnou provincii.

Vzniknou sloupce:
- `is_capital_province` (0/1)
- `capital_city_name`

### 6.3 Cisteni geometrie
- odstranuji se vnitrni diry (`remove_holes`),
- znovu se dela topologicka oprava (`buffer(0)`),
- dela se `land_union` (sjednocena pevnina).

### 6.4 Slucovani malych provincii
Funkce `merge_small_absolute`:
- jede po statech,
- pokud ma provincie plochu pod `MIN_AREA_ABS = 1_000_000_000`,
- slouci ji s nejblizsi provincii stejne zeme.

Dulezite:
- pri merge se prenasi i info o hlavnim meste (`is_capital_province`, `capital_city_name`).

### 6.5 Generace morskych regionu
Postup:
1. Udela se obalka kolem pevniny.
2. Odecte se pevnina -> zbyde more.
3. V mori se vygeneruje az 15000 nahodnych bodu.
4. Body se seskupuji pomoci `KMeans` na `N_REGIONS = 60` center.
5. Nad centry se spocte Voronoi diagram.
6. Voronoi bunky se orezou na more a lehce vyhladi `buffer(+15000).buffer(-15000)`.

Vysledek: `final_regions` = morske provincie.

### 6.6 Preview
Vytvori se `preview_map.png` pro rychly vizualni check.

### 6.7 Predani do exportu
Nakonec se vola:

```python
run_export(land, final_regions)
```

To je vstup do hlavni exportni casti.

## 7. Co dela `export_to_opengs.py`

### 7.1 `export_province_map`
Vytvori `ProvinceMap.png` (4096x4096):
- kazda pevninska provincie dostane unikatni RGB,
- kazdy morsky region taky dostane unikatni RGB.

Vraci:
- `province_colors` (mapa barva -> `pid`),
- `bounds` (pro prevody souradnic).

### 7.2 `export_id_map`
Tohle je technicky klicova cast.

Co dela:
- nacte `ProvinceMap.png`,
- sestavi LUT `256x256x256` pro mapovani RGB -> ID,
- morskym barvam priradi stabilni sea ID (`max_pid + 1`, `+2`, ...),
- vyrobi `ProvinceIDMask.png` (a alias `ProvinceMask.png`).

Kodovani ID do RGB:
- `R = id & 0xFF`
- `G = (id >> 8) & 0xFF`
- `B = (id >> 16) & 0xFF`

Bezpecnost:
- pokud ID > `16777215` (`0xFFFFFF`), export failne jasnou chybou.

### 7.3 `export_political_map`
- kazdy stat dostane nahodnou barvu,
- provincie se obarvi podle statu,
- more zustane v `SEA_COLOR`.

Vysledek: `PoliticalMap.png`.

### 7.4 `export_provinces_txt`
Generuje hlavni runtime tabulku `Provinces.txt`.

Hlavicka:

`id;R;G;B;type;state;owner;controller;x;y;province_name;country_name;population;gdp;gdp_per_capita;is_capital;capital_city;neighbors;ideology`

Jak se vyplnuje:
- `type` je `land` nebo `sea`,
- `x,y` je centroid provincie v pixelech (sea ma `0,0`),
- `population/gdp/ideology` berou data z import modulu,
- `neighbors` se pocitaji z hranic pixelu v ID mape.

### 7.5 Jak vznikaji `neighbors`
Algoritmus jede nad matici ID:
1. Porovna horizontalni sousedy pixelu.
2. Porovna vertikalni sousedy pixelu.
3. Kde je rozdil ID, tam je hranice mezi dvema provinciemi.
4. Dvojice se deduplikuji a ulozi obousmerne.

Proc je to dobre:
- je to rychle,
- odpovida to presne rasteru, se kterym pracuje hra.

### 7.6 Dalsi exporty
- `Population.txt`
- `GDP.txt`
- `Ideology.txt`
- `ProvincePopulationLookup.json`
- `States.txt`
- `States/*.txt`

## 8. Tematicke mapy (`export_theme_map.py`)

### 8.1 Obecny princip
`export_theme_map`:
- jde pixel po pixelu,
- podle `id_map` hleda barvu provincie,
- more barvi konstantne (`SEA_COLOR`),
- prekresli morske obrysy,
- ulozi final PNG.

### 8.2 GDP mapa
`export_gdp_map`:
- pokud jsou GDP data, bere logaritmickou skalu (`log10`),
- gradient od svetle piskove po tmave cervenou,
- kdyz data chybi, spadne to do fallback barev.

### 8.3 Population mapa
`export_population_map`:
- idealne pracuje s hustotou (`population / km2`),
- ma globalni log skalu,
- u imputovanych dat jemne micha globalni/lokalni kontrast,
- barvy od svetle po tmave zelenou.

### 8.4 Ideology mapa
`export_ideology_map`:
- kanonicke labely: `demokracie`, `kralovstvi`, `autokracie`, `unknown`.

Fixni barvy:
- demokracie = modra
- kralovstvi = zlata
- autokracie = cervena
- unknown = seda

### 8.5 Rezimy `Modes/*`
`export_mode_folder`:
- mapu presune do `Modes/<Mode>/`,
- vytvori `manifest.txt` a `meta.json`,
- pokud je cilovy PNG lockly, vytvori fallback soubor s timestampem.

## 9. Populace (`import_population.py`) lidsky a vecne

### 9.1 Co je na tom tezke
Populacni data z realu jsou casto bordel:
- jine nazvy regionu,
- jiny jazyk,
- ruzna administrativa,
- obcas stara data,
- nekde chybi `iso`.

Proto je modul hodne robustni.

### 9.2 Match priority
Priorita matchingu:
1. `iso`
2. `exact_country`
3. `region_only`
4. `fuzzy_contain`
5. `fuzzy_best`

Kdyz je kolize, bere se lepsi priorita nebo novejsi datum.

### 9.3 Konzistentni distribuce
`USE_CONSISTENT_DISTRIBUTION = True`.

To znamena:
- existujici matchovane provincie zachova,
- chybejici dopocte,
- umi kalibrovat na ofiko country totals,
- pro `FRA/ESP/GBR` ma specialni region-guided strategii.

### 9.4 Dulezite konstanty
- `TARGET_POP_YEAR = 2023`
- `MIN_POP_YEAR = 2000`
- `FORCE_SEED_ONLY_COUNTRIES = {"FRA", "ESP", "GBR"}`
- `FORCE_WEIGHT_EXPONENT = 0.85`

## 10. GDP (`import_gdp.py`) jednoduse
Pravidla pro kazdou zemi:

1. Kdyz je `gdp_total` -> rozdeli se mezi provincie podle podilu populace.
2. Kdyz neni `gdp_total`, ale je `gdp_per_capita` -> `gdp = gdp_per_capita * population`.
3. Kdyz neni nic -> `gdp = 0`.

Parser je robustni:
- zvlada desetinnou carku,
- zvlada hlavickovy i bezhlavickovy CSV.

## 11. Ideologie (`import_ideology.py`) jednoduse
- bere country ideologii a prenasi ji na provincie.
- umi mapovat synonyma na kanonicke labely.

Kanonicke vystupy:
- `demokracie`
- `kralovstvi`
- `autokracie`
- `unknown`

## 12. Co presne najdes ve vystupu (`opengs_export`)
Typicky:
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

## 13. Dulezite formaty dat

### 13.1 `Provinces.txt`
Sloupce:
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
Kazdy radek:

`ISO3;R;G;B`

### 13.3 `Population.txt`
`id;population;population_source;population_date;source_region;source_country;match_method`

### 13.4 `GDP.txt`
`id;gdp;gdp_per_capita;gdp_source;gdp_year`

### 13.5 `Ideology.txt`
`id;ideology;ideology_source;ideology_year`

## 14. Jedna provincie od startu az do hry
At je jasne, co se deje "s jednim kusem mapy":

1. Prijde ze shapefile.
2. Projde filtrem Evropy.
3. Opravi se geometrie.
4. Pripadne se slouci (kdyz je moc mala).
5. Dostane unikatni barvu v `ProvinceMap`.
6. Dostane ciselne ID v `ProvinceIDMask`.
7. Dostane populaci (match nebo imputace).
8. Dostane HDP.
9. Dostane ideologii.
10. Dostane seznam sousedu.
11. Zapise se jako radek do `Provinces.txt`.
12. Hra to pak nacte a pouzije.

## 15. Nejcastejsi problemy a co s nimi

### 15.1 `country_gdp_totals.csv not found`
Co to znamena:
- chybi GDP vstup.

Co udelat:
1. Dodat `country_gdp_totals.csv` do `build_map/src`.
2. Overit sloupce (`country_iso3` + `gdp_total` nebo `gdp_per_capita`).
3. Spustit znovu.

### 15.2 Moc `unmatched` v populaci
Co to znamena:
- regiony z `query.csv` se spatne sparovaly.

Co udelat:
1. Zkontrolovat `regionLabel`/`countryLabel`.
2. Dodat aliasy do `population_aliases_starter.csv`.
3. Pokud jde, doplnit `iso`.
4. Porovnat `Population_debug.csv` pred/po.

### 15.3 `PermissionError` pri PNG
Co to znamena:
- soubor je lockly jinou appkou.

Co udelat:
1. Zavrit nahled obrazku.
2. Spustit znovu.
3. U `Modes/*` je fallback soubor, ale lock je lepsi odstranit.

### 15.4 Mapa vypada prazdna
Co to znamena:
- problem ve vstupnim shapefile nebo v orezu.

Co udelat:
1. Overit vsechny shapefile casti (`.shp/.dbf/.shx/.prj`).
2. Overit, ze nejsou poskozene.
3. Zkontrolovat casti `PART 1` a `PART 2` v logu.

### 15.5 Rozbite znaky v textu
Co to znamena:
- soubor byl otevren/vygenerovan ve spatnem kodovani.

Co udelat:
1. Otevirat jako UTF-8.
2. Neprepisovat exporty v ANSI.

## 16. Rychla kontrola po behu (60 sekund)
1. Existuje `ProvinceMap.png` a `ProvinceIDMask.png`.
2. `Provinces.txt` ma jak `land`, tak `sea` radky.
3. Je aspon jedna provincie s `is_capital=1`.
4. `Population.csv` neni prazdny.
5. `GDP.csv` neni cely v nulach.
6. Ve `Modes/*` je `manifest.txt` a `meta.json`.

## 17. Proc je to navrzene zrovna takhle (obhajoba)
Nejbeznejsi argumenty:

1. Projicovani do `EPSG:3035`
- potrebuju metricke jednotky na plochu a vzdalenost.

2. Orez Ruska
- bez toho by byla evropska mapa prostorove nevyvazena.

3. Merge mini provincii
- stabilnejsi raster + hratelnejsi mapa.

4. Voronoi more
- automaticka tvorba morskych regionu bez manualniho kresleni.

5. ID maska 24-bit
- rychly a presny runtime lookup pixel -> province ID.

6. Robustni match populace
- realny data source je neporadek, takze musi byt fallbacky.

## 18. Mini mluvene vystoupeni (3-5 minut)
Kdyz to chces odrikat jednoduse:

1. "Nejdriv nactu admin mapu Evropy a prehodim ji do metricke projekce."
2. "Data geometrii vycistim, orezu na Evropu a sloucim moc male regiony."
3. "Pro more automaticky vygeneruju regiony pres KMeans + Voronoi."
4. "Pak vyrabim mapove vrstvy: ProvinceMap, ID masku a political mapu."
5. "Nad tim dopoctu populace, GDP a ideologii po provinciich."
6. "Nakonec exportuju runtime tabulky (`Provinces`, `States`) a tematicke mapy do slozek `Modes`."
7. "Cely pipeline ma fallbacky, takze i pri nekompletnich datech export bezi a vystupy jsou konzistentni."

## 19. Tahak: jedna veta kdyz te prerusi
"Projekt prevadi geodata a statistiky do hotovych hernich mapovych podkladu (PNG + TXT/CSV/JSON), vcetne robustniho matchingu a fallbacku pro chybna data."

## 20. Pseudokod celeho flow
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

## 21. Vysvetlivky pojmu (po lopate)
- `Voronoi diagram`: rozdeleni plochy podle nejblizsiho stredu. V projektu to znamena, ze more se automaticky rozdeli na regiony podle center z KMeans.
- `KMeans`: algoritmus, co rozdeli body do `N` skupin a najde jejich stredu. Tady se pouziva pro vyber center morskch regionu.
- `CRS`: Coordinate Reference System, tedy jak jsou mapove souradnice definovane.
- `EPSG:3035`: evropsky metricky CRS. Diky tomu jsou plochy a vzdalenosti v metrech, ne ve stupnich.
- `bbox` (bounding box): obdelnikovy ramec, kterym se data orezavaji na zajimavou oblast.
- `Polygon` a `MultiPolygon`: jeden uzavreny tvar vs. vice tvaru pod jednim zaznamem.
- `buffer(0)`: bezny trik na opravu nevalidnich geometrii.
- `land_union`: spojeni vsech pevninskych geometrii do jednoho celku.
- `raster` vs `vektor`: raster = pixely (`.png`), vektor = geometrie (`.shp`, polygonove tvary).
- `centroid`: stred oblasti; v exportu se uklada jako `x,y` v pixelech.
- `PID` (province ID): cislo provincie pouzivane v tabulkach a maskach.
- `LUT` (lookup table): predpripravena tabulka pro rychle mapovani hodnot, tady RGB -> province ID.
- `24-bit ID kodovani`: ID se rozdeli do tri bajtu a ulozi do `R,G,B`.
- `neighbors`: sousedni provincie, zjistene podle sdilenych hranic pixelu v ID mape.
- `imputace`: dopocet chybejici hodnoty (napr. populace), kdyz data chybi.
- `fallback`: zalozni postup, kdyz hlavni postup neni mozny.
- `region-guided`: rozdeleni podle regionovych aggregatek, kdyz prime matchovani neni spolehlive.

## 22. Vysvetlivky knihoven (k cemu jsou)
### 22.1 Externi knihovny z `requirements.txt`
- `geopandas`: tabulkova prace s geodaty (GeoDataFrame), nacitani shapefile, reprojekce, filtrovani.
- `shapely`: geometricke operace nad tvary (prunik, sjednoceni, vzdalenosti, buffery).
- `pyproj`: prevody mezi souradnicovymi systemy.
- `rtree`: prostorovy index pro rychlejsi geometrii dotazy.
- `numpy`: rychla prace s maticemi/pixely (`id_map`, obrazove pole).
- `pandas`: prace s tabulkami CSV/TXT (cteni, transformace, zapis).
- `matplotlib`: tvorba nahledu (`preview_map.png`).
- `scikit-learn`: `KMeans` clustering pro morske regiony.
- `pillow` (`PIL`): cteni/zapis obrazku a kresleni do PNG map.

### 22.2 Dulezite standardni moduly Pythonu
- `os`: cesty a prace se soubory/slozkami.
- `json`: zapis/cteni JSON (`meta.json`, lookup soubory).
- `random`: nahodne barvy a nahodne body v mori.
- `re`: regularni vyrazy pro cisteni/normalizaci textu.
- `difflib`: fuzzy porovnavani nazvu regionu.
- `unicodedata`: sjednoceni textu bez diakritickych rozdilu.
- `math`: logaritmy a ciselne prevody pro tematicke mapy.
- `glob`: hledani souboru podle patternu (`query*.csv`).
- `time`/`shutil`: fallback export kdyz je cilovy PNG lockly.

## 23. Zkratky a nazvy v dokumentaci
- `GDP`: Gross Domestic Product (HDP).
- `PID`: Province ID.
- `CRS`: Coordinate Reference System.
- `EPSG`: registry kodu souradnicovych systemu.
- `ISO3`: 3pismenny kod statu (`CZE`, `DEU`, ...).
- `ISO 3166-2`: kod regionu uvnitr statu.
- `WDQS`: Wikidata Query Service.
- `LUT`: lookup table.
- `CSV`: textova tabulka oddelena oddelovacem.
- `TXT`: textovy export bez slozite struktury.
- `JSON`: strukturovany textovy format pro data.
- `PNG`: bezztratovy obrazkovy format.
- `venv`: virtualni Python prostredi.
- `bbox`: bounding box (obdelnikovy orez).
- `seed`: pocatecni vaha/hodnota pro vypocet.
- `unknown`: fallback hodnota, kdyz data chybi.

## 24. Co je "import" a "export" v tomhle projektu
### 24.1 Import (nacitani a priprava dat)
V tomhle projektu `import` znamena: vzit externi data, vycistit je, normalizovat a pripravit pro vypocet po provinciich.

Hlavni import moduly:
- `import_population.py`: nacita populaci, matchuje regiony, imputuje chybejici hodnoty, kalibruje na official totals.
- `import_gdp.py`: nacita country GDP a prepocita ho na provincie.
- `import_ideology.py`: nacita country ideologii a priradi ji provinciim.

### 24.2 Export (zapis finalnich vystupu)
`Export` znamena: vzit uz zpracovana data a ulozit je do souboru, ktere umi cist hra.

Hlavni export vrstva:
- `export_to_opengs.py`: orchestruje vsechny exporty.
- `export_political_map.py`: uklada `PoliticalMap.png`.
- `export_theme_map.py`: uklada tematicke mapy + `Modes/*` metadata.

Typicke exportovane soubory:
- `ProvinceMap.png`, `ProvinceIDMask.png`, `ProvinceMask.png`
- `PoliticalMap.png`, `GDPMap.png`, `PopulationMap.png`, `IdeologyMap.png`
- `Provinces.txt`, `States.txt`, `States/*.txt`
- `Population.csv/.txt`, `GDP.csv/.txt`, `Ideology.csv/.txt`
- `ProvincePopulationLookup.json`

## 25. Jak cist "importy" mezi Python soubory (module flow)
Prakticka orientace v tom, kdo koho vola:

- `build_map.py` importuje `run_export` z `export_to_opengs.py`.
- `export_to_opengs.py` importuje:
  - `export_political_map` z `export_political_map.py`,
  - `export_gdp_map`, `export_population_map`, `export_ideology_map` z `export_theme_map.py`,
  - `generate_population_dataset` z `import_population.py`,
  - `generate_gdp_dataset` z `import_gdp.py`,
  - `generate_ideology_dataset` z `import_ideology.py`.

Jinymi slovy:
- `build_map.py` = hlavni ridic,
- `import_*` = data priprava,
- `export_*` = ulozeni do runtime formatu.

---
Dokumentace je psana podle aktualni implementace ve slozce `build_map/src` k datu 2026-03-16.
Formulovani textu pomahalo AI.
