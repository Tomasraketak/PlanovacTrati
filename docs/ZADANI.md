# Upřesněné zadání a vývojové podmínky

## 1. Cíl

Program, který nad volně dostupnými daty (výškový model terénu + OpenStreetMap) **automaticky navrhne osu
vysokorychlostní trati** mezi zadanými body, spočítá **orientační cenu**, **jízdní doby**, vypíše **statistiku
staveb** (tunely, estakády, mosty, zemní práce, demolice) a vykreslí **interaktivní mapu** a **podélný profil**.
Ovládání přes přehledné webové GUI v prohlížeči, výpočet lze spustit i z příkazové řádky.

Typické použití: „Navrhni trať na 200 km/h České Budějovice – Třeboň – Jindřichův Hradec – Jihlava, max. sklon 25 ‰,
co nejméně tunelů a estakád, ať se nebourají domy a trať se vyhýbá obcím bez zastávky, prodloužení proti vzdušné
čáře max. 20 %.“

## 2. Vstupy (vše měnitelné v GUI i v YAML souboru projektu)

| Skupina | Parametr | Výchozí |
|---|---|---|
| Trasa | seznam bodů v pořadí: název, souřadnice, typ **stanice** / **průjezdní bod** | – |
| Návrh | návrhová rychlost | 200 km/h |
| | max. podélný sklon | 25 ‰ |
| | max. sklon ve stanici, délka nástupiště | 2 ‰, 400 m |
| | **max. prodloužení proti vzdušné čáře** (pro každý úsek mezi body) | 20 % |
| | převýšení D, nedostatek převýšení I → min. poloměr oblouku | 150 mm, 100 mm |
| | limity násypů/zářezů, od kdy estakáda / tunel | 15 m / 20 m / 8 m / 15 m |
| Priority | váhy: obce, budovy, terén (tunely+estakády), voda, chráněná území, délka | 1,0 |
| Ceny | jednotkové ceny všech typů staveb, demolic, pozemků, rezerva | viz `config.py` |
| Vlak | předvolba (RegioPanter, Railjet, Pendolino, ICE 3, TGV) nebo vlastní parametry; pobyt v zastávce, rezerva | ICE 3, 90 s |
| Snížená rychlost | max. počet a délka úseků, min. rychlost, prahy úspory (mil. Kč / domy) | 4 × 3 km, 120 km/h, 300 mil. / 5 |
| Demolice | penalizace zbourání domu pro optimalizaci | +40 mil. Kč/dům |
| Souběh | tolerance a sleva u stávající trati, vzdálenost a sleva u silnic | ±4 m −50 %, 10 m −25 % |
| Linky | název, stanice zastavení (zastávkový / expres / vybrané) | 3 linky |
| Výpočet | rozlišení rastru, demo režim, stahování budov a chráněných území, vlastní DEM | 50 m |

Body se zadávají kliknutím do mapy, vyhledáním názvu (Nominatim) nebo ručně souřadnicemi.

## 3. Výstupy

1. **Interaktivní mapa** – osa obarvená podle typu stavby, stanice s časy, demolice, vzdušná čára, kilometrovník,
   přepínatelné podklady (OSM, topografická, satelit), nákladová mapa jako volitelná vrstva.
2. **Podélný profil** (terén × niveleta, barevné úseky), **graf sklonů**, **rychlostní profil**.
3. **Statistika staveb** – počet a délky tunelů (ražených i hloubených), estakád, mostů; nejdelší objekt; seznam
   všech objektů se staničením; objemy násypů a výkopů; zábor; počet demolic a budov v pásmu 100 m;
   křížení silnic, železnic a vodních toků; obce v blízkosti trati; průchod chráněnými územími.
4. **Rozpočet** po položkách + projekce + rezerva, cena celkem a na km.
5. **Jízdní řád** (příjezd/odjezd), jízdní doby úseků, průměrná rychlost, varianta bez zastavení, porovnání 5 vlaků.
6. **Úseky se sníženou rychlostí** – poloha, rychlost, poloměr, úspora, zachráněné domy, ztráta času.
6. **Exporty**: HTML report (vše v jednom souboru), GeoJSON, KML (Google Earth, 3D niveleta), CSV profil (Excel),
   projekt YAML, ZIP se vším.

## 4. Funkční požadavky

- F1 Trasa musí projít všemi zadanými body; ve stanicích je přímá a vodorovná v délce nástupiště.
- F2 Žádný úsek mezi sousedními body nesmí být delší než `(1 + p) × vzdušná vzdálenost` (p = limit prodloužení);
  nelze-li to splnit, program to oznámí.
- F3 Max. sklon nivelety ≤ zadaný limit všude; ve stanicích ≤ limit pro stanice.
- F4 Poloměry směrových oblouků ≥ R_min = 11,8·V²/(D+I); pokud to zadané body neumožní, program to oznámí
  a v jízdní době zohlední sníženou rychlost.
- F5 Optimalizace minimalizuje součet: délka + tunely/estakády/zemní práce + demolice + průchod obcemi bez
  zastávky + voda + chráněná území, s váhami nastavitelnými uživatelem.
- F6 Okolí stanic (nastavitelný okruh) se za zástavbu nepenalizuje – trať do měst se zastávkou vést má.
- F7 Výpočet běží s ukazatelem průběhu, chyby se zobrazí srozumitelně česky.
- F8 Projekt lze uložit/načíst (YAML), přednastaven projekt ČB – JH – Jihlava a demo projekt.

## 5. Vývojové podmínky (nefunkční požadavky)

- Python ≥ 3.10; Windows 10/11 (hlavní platforma), Linux, macOS. Pouze knihovny s hotovými wheely
  (numpy, scipy, pandas, rasterio, pyproj, shapely, scikit-image, streamlit, folium, plotly).
- Instalace, spuštění a aktualizace jedním příkazem/dvojklikem (`install.bat`, `run.bat`, `update.bat`
  a `.sh` varianty).
- Data se stahují automaticky (Copernicus DEM GLO-30 z AWS, Overpass API, Nominatim) a ukládají do
  `data/cache/` → opakovaný výpočet funguje offline. Přetížené Overpass servery: opakování + záložní servery;
  při selhání vrstva vynechána s varováním (výpočet nespadne).
- Oblast ~100 × 75 km při 50 m se spočítá řádově za 1–3 minuty (bez stahování dat). Příliš velká oblast →
  automatické zhrubnutí rastru.
- Výpočetní jádro (`planovac/`) je nezávislé na GUI → použitelné z CLI, skriptů a testů.
- Automatické testy (`pytest`) běží bez internetu na syntetickém terénu.
- UI, dokumentace, hlášky i komentáře v češtině.

## 6. Vědomá zjednodušení

- Přechodnice a vzestupnice nejsou modelovány (vliv na délku i cenu je malý).
- Výškový model má rozlišení ~30 m (DSM – u lesa zahrnuje výšku stromů); pro detail lze použít vlastní DMR 5G.
- Data OSM nemusí být úplná (budovy, chráněná území); demolice jsou odhad podle středů budov.
- Ceny jsou orientační (±40 %), vhodné pro porovnání variant, ne pro rozpočet stavby.
- Jízdní doba: model hmotného bodu, bez vlivu napájení, návěstidel a ETCS křivek.
- Nejde o projektovou dokumentaci – výsledek je **koncepční studie** pro diskusi a porovnání variant.
