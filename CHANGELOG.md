# Changelog

## [1.1.1] — 2025-04-05

### Fixed

- **Černé moře zmizelo** — funkce `_erase_inland_sea_components()` mazala všechny
  mořské komponenty, které se nedotýkaly okraje rastru, včetně legitimních uzavřených
  moří (Černé moře, Kaspické moře). Přidán limit `INLAND_SEA_MAX_ARTIFACT_PIXELS = 5000`:
  velké uzavřené mořské komponenty (> 5 000 px) se zachovají, pouze malé artefakty
  se přebarvují na sousední pevninu.

- **Sea → sea pohyb nefungoval** — část mořských provincií měla po filtrech (`SEA_TO_SEA_MIN_SHARED_EDGES`,
  `_sea_anchor_line_crosses_land`) nulový počet mořských sousedů. Lodi v takové
  provincii se nemohly pohybovat na sousední mořskou provincii. Opraveno dvoustupňovým
  fallbackem v exportu (`export_to_opengs.py`):
  1. Pokud izolosvané mořské provincii zbývá alespoň jeden původní dotyk s jinou
     mořskou provincií (pair_counts), obnoví se nejsilnější z nich (nejvíce sdílených
     hran) za předpokladu, že přímá čára anchor → anchor nepřechází přes pevninu.
  2. Pokud žádný původní dotyk nepřežije, nalezne se nejbližší legální mořská
     provincie (vzdálenost anchor-to-anchor, max. 40 pixelů tolerovaného průchodu
     pevninou) a propojí se s ní.

- **Inland sea corridor přes střední Evropu** — mořské provincie generované
  Voronoi algoritmem zasahovaly do vnitrozemí (Maďarsko, Slovensko, …), čímž
  vznikala nerealitická cesta `sea → sea` přes pevninu. Opraveno kombinací:
  - `INLAND_NO_SEA_COUNTRIES` maska v `build_map.py` (vektor, generace moře),
  - `SEA_TO_SEA_MIN_SHARED_EDGES = 8` v `export_to_opengs.py` (min. dotyk 8 px),
  - `_erase_inland_sea_components()` (vektorizovaný rasterový cleanup),
  - post-export smazání mořských sousedů pro vnitrozemské provincie.

- **Vnitrozemské státy měly mořské sousedy** — AUT, HUN, SVK, CZE, CHE, LUX,
  BLR, MDA, SRB, MKD dostávaly v `Provinces.txt` zbytečné mořské sousedy.
  Tyto vazby jsou nyní odstraněny už při exportu.

- **AEO (Adam Epstein Ostrov) nebyl viditelný** — provincie měla po cleanup
  passech příliš málo pixelů. Tvar přepracován na text "EPSTEIN" (funkce
  `_text_to_shapely_geom()`), šířka 190 km → ~2090 px; pozice Faeroe ostrovy.

### Changed

- `_build_neighbor_lookup()` nyní volitelně vrací i `pair_counts` (počty sdílených
  hran pro každý pár provincií) přes parametr `return_pair_counts=True`. Slouží
  jako základ pro fallback popsaný výše.

### Removed / Cleanup

- Smazán adresář `opengs_export/ArmyIcons - kopie/` a všechny ostatní Windows
  Explorer zálohy (`* - kopie.*`, `* - kopie/`) ze sledování Gitu.
- Přidán `.gitignore` pokrývající build logy (`_build_log.txt`, `_build_err.txt`),
  Python bytecode, venv a Windows Explorer kopie.

---

## [1.1.0] — 2025-04-04 (stable build)

- Stabilní základní build s Voronoi mořem, super-samplovaným rastrem, exportem
  Provinces.txt, všemi tematickými mapami a opravou port-adjacency.

## [1.0.2] — předchozí

## [1.0.1] — předchozí

## [1.0.0] — první veřejný release
