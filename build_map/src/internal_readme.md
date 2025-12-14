✅ INTERNAL README — map_generator_godot

(TENTO README JE URČENÝ PRO x Slouží jako technický popis celého projektu, pipeline a datových struktur.)

📌 1. Co projekt dělá

Projekt map_generator_godot je Python nástroj, který generuje veškeré mapové podklady pro Godot grand-strategy hru:

ProvinceMap.png – každá provincie má unikátní RGB, beze ztráty.

ProvinceMask.png – mapování pixelů → province ID.

PoliticalMap.png – barevná mapa států.

GDPMap.png, PopulationMap.png, IdeologyMap.png – tematické mapy.

Provinces.txt – velký výpis všech provincií a parametrů.

States.txt a složka /States/ s definicí každého státu.

Modes/ pro jednotlivé typy map (GDP, Ideology, Population).

Projekt používá Natural Earth admin 1 provinces, reprojekci do EPSG 3035, a kombinuje je s vlastním řezem Ruska, přidáním ostrovů a generovanými mořskými regiony (Voronoi).

📌 2. Celý pipeline (krok za krokem)
STEP 1 — Load + filter Europe

File: build_map.py

Načte ne_10m_admin_1_states_provinces.shp

Převede na EPSG:3035

Odfiltruje pouze evropské státy:

EUROPE_COUNTRIES = [ISL, IRL, GBR, ... , UKR, BLR, RUS, ARM, GEO, AZE, TUR]


Rusko se odřízne na evropskou část bounding boxem.

Vše se ořízne na evropský bounding box, aby zůstaly ostrovy, Caucasus, Iceland.

Výsledek: admin = čisté, základní provincie.

STEP 2 — Cleaning geometry

Odstranění vnitřních děr (remove_holes)

Buffer(0) pro fix invalid geom

Spojení celého land union (land_union)

STEP 2.5 — Merging of small regions

Každá provincie s plochou < 1 000 000 000 m² se sloučí s nejbližší sousední provincií dané stejné země.

Výsledek: land = finální provincie pro rasterizaci.

STEP 3 — Sea region generation

Vytvoří se bounding box okolo Evropy

Vygeneruje se ~15000 náhodných bodů v moři

Ty se clustrují pomocí KMeans

Z center clusterů se vytvoří Voronoi diagram

Každá Voronoi buňka se:

ořízne na moře

vyhladí (buffer ±15000)

Výsledek: sea_regions (Polygon/MultiPolygon list).

STEP 4 — Preview

Vygeneruje se nepodstatný obrázek preview_map.png.

STEP 5 — Export to OPENGS format

Zde začíná hlavní export.

🔹 5.1 export_province_map()

Každé provincii se přidělí unikátní RGB (100% garance žádné duplicity).

Sea Voronoi regiony také dostanou unikátní RGB.

Výstup:

ProvinceMap.png

province_colors dict: { (R,G,B): province_id }

bounds pro rasterizaci v dalších krocích.

🔹 5.2 export_id_map()

Vytvoří se 3D LUT (256×256×256) mapující RGB → province ID.

Výstup:

ProvinceMask.png – každý pixel obsahuje ID provincie zakódované jako:

R = ID % 256

G = ID // 256

B = 0

id_map – numpy 2D array (H×W) s ID.

🔹 5.3 export_political_map()

Každý stát dostane náhodnou barvu.

Provincii se přiřadí barva státu podle land["country"].

Sea zůstává modrá.

Nakreslí se mořské hranice (Voronoi).

Výstup: PoliticalMap.png

🔹 5.4 export_provinces_txt()

Generuje nejdůležitější výstup:

id;R;G;B;type;state;owner;controller;x;y


Kde:

id = index provincie

R,G,B = unikátní barva z ProvinceMap

type = land/sea

x,y = centroid provincie v pixelových souřadnicích

Výstup: Provinces.txt

🔹 5.5 export_states() + export_state_files()

Vytvoří:

States.txt
CZE;123;145;200
DEU;44;90;110
...


Každý stát má vlastní náhodnou barvu.

/States/

Soubor pro každý stát:

1_CZE.txt

state={
    id=1
    name="STATE_CZE"
    provinces={
        120
        121
        122
    }
}

🔹 5.6 Thematic maps (via export_theme_map.py)

Každá mapa:

načte id_map

každé provincii dá hodnotu (random RGB dle tématu)

nakreslí Voronoi hranice moře

uloží PNG

vytvoří mód složku:

opengs_export/Modes/GDP/
   GDPMap.png
   manifest.txt
   meta.json


Stejný princip pro:

GDPMap

PopulationMap

IdeologyMap

📌 3. Klíčové moduly a jejich zodpovědnost
Soubor	Funkce
build_map.py	kompletní pipeline: načtení dat, čištění, merge, generace moře, preview, export
export_to_opengs.py	hlavní exportní hub pro všechny mapy
export_shared.py	konstanty, rasterizační funkce, konverze geom → pixely
export_political_map.py	generuje PoliticalMap
export_theme_map.py	generuje thematic maps (GDP, Population, Ideology)
import_population.py	zpracování population datasetu (zatím nepropojeno ve výše uvedeném)
NUTS_… files	originální data z EU (možné budoucí použití)
ne_10m_admin_1_states_provinces.shp	hlavní zdroj administrativních provincií
📌 4. Výstupní struktura projektu
opengs_export/
   ProvinceMap.png
   ProvinceMask.png
   PoliticalMap.png
   Provinces.txt
   States.txt
   /States/
       1_CZE.txt
       2_DEU.txt
       ...
   /Modes/
       /GDP/
          GDPMap.png
          meta.json
          manifest.txt
       /Population/
          PopulationMap.png
          ...
       /Ideology/
          IdeologyMap.png
          ...


Vše je 100% kompatibilní s Godot loaderem, který využívá:

ProvinceMap → identifikace kliků

ProvinceMask → rychlé lookupy

PoliticalMap → UI

Modes → přepínatelné herní mapy

Provinces.txt + States.txt → datové tabulky hry

📌 5. Co si musí AI zapamatovat, když dostane tento README

Když mi vložíš tento READ ME v jiném chatu:

✔ Hned poznám:

jak pipeline funguje

jaké soubory projekt generuje

jak jsou propojené

jak má Godot číst výsledky

kde hledat bug při exportu

jak upravit pythony tak, aby generovaly nové typy map

jak přidat nové datové vrstvy (GDP z CSV, reálná populace, atd.)

jak přemapovat provincie, státy nebo mořské regiony

Tohle README je v podstatě knowledge capsule celého projektu.

📌 6. Pokud chceš, doplním:

detailní UML diagram

datový diagram ID toků (RGB → PID → STATE → MODE)

pseudokód pipeline

ASCII mapu struktury projektu

dokumentaci Godot loaderu