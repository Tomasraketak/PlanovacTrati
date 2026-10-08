# Jak to funguje (metodika)

Výpočet probíhá v 8 krocích (`planovac/pipeline.py`). Vše se počítá v metrických souřadnicích UTM 33N
(EPSG:32633), které pokrývají celé Česko.

```
body trasy ─► oblast ─► DEM + OSM ─► nákladová mapa ─► koridor (Dijkstra) ─► oblouky ─► niveleta (DP)
                                                                                         │
           report ◄── jízdní doby ◄── rozpočet ◄── stavby, demolice, křížení ◄──────────┘
```

## 1. Oblast výpočtu
Pro každý úsek mezi sousedními body se spočítá **elipsa** s ohnisky v těchto bodech a součtem vzdáleností
`(1 + p) · d` (p = povolené prodloužení). Libovolná trasa, která by elipsu opustila, by byla delší než limit,
takže se mimo elipsy vůbec nehledá. Oblast = obálka elips + okraj.

## 2. Data
- **Výškový model**: Copernicus DEM GLO-30 (dlaždice 1°×1°, ~30 m), převzorkovaný na zvolené rozlišení
  (výchozí 50 m). Alternativně vlastní GeoTIFF (např. DMR 5G ČÚZK).
- **OpenStreetMap** (Overpass API; záložně **Overture Maps** přes `planovac/zdroje.py`, čtení parquet po řádkových skupinách): zástavba (landuse), obce, vodní plochy a řeky, silnice I./II. třídy, dálnice,
  železnice, chráněná území a středy budov.

## 3. Nákladová mapa (`costsurface.py`)
Každá buňka rastru dostane „cenu za metr trati“ (1 = trať v rovině v polích):

| složka | penalizace |
|---|---|
| zástavba obce | +25 uvnitř, pás 300 m klesající od +6 |
| jednotlivé budovy | podle hustoty budov (samoty, chaty) |
| terén | sklon terénu vůči max. sklonu trati + lokální převýšení v okně 600 m |
| voda | +6 vodní plocha, +1,5 řeka |
| chráněná území | +12 NP/NPR, +4 rezervace/Natura, +0,8 CHKO |

Každá složka je vynásobena **vahou** z GUI. V okruhu kolem **stanic** (výchozí 2 km) se zástavba a budovy
nepenalizují – trať do města se zastávkou vést má. Průjezdní body výjimku nemají.

## 4. Koridor (`corridor.py`)
1. **Dijkstra** (scikit-image `MCP_Geometric`, 8-sousednost) najde nejlevnější cestu rastrem v elipse.
2. **Natahování provázku**: schodovité úseky cesty se nahradí přímkou, pokud tím celková cena nevzroste – vzniká
   lomená čára s libovolnými směry.
3. **Limit prodloužení**: je-li cesta delší než `(1+p)·d`, přičte se ke každému metru Lagrangeův multiplikátor λ
   (tlak na kratší trasu) a bisekcí se najde nejmenší λ, při kterém je limit splněn.

## 5. Směrové řešení (`horizontal.py`)
- Minimální poloměr **R_min = 11,8·V² / (D + I)** (200 km/h, D = 150 mm, I = 100 mm → 1 900 m),
  doporučený poloměr pro D = 100, I = 60 mm (→ 3 000 m).
- Lomená čára se zjednoduší (Douglas–Peucker) na vrcholy. Zadané mezilehlé body se nahradí dvojicí vrcholů
  ve směru osy, takže stanice leží **na přímé** (nástupiště).
- Do každého vrcholu se vloží kružnicový oblouk s co největším poloměrem (≤ doporučený), který se vejde mezi
  sousední oblouky. Pokud se nevejde ani R_min, odstraní se vrchol s nejmenší odchylkou a postup se opakuje.

## 6. Výškové řešení – niveleta (`vertical.py`)
**Dynamické programování**: stav = (poloha po 25 m, výška nivelety v diskrétních hladinách). Mezi sousedními
polohami se výška smí změnit maximálně o `max. sklon × 25 m` (ve stanicích téměř nic). Cena polohy = cena 1 m trati
při výšce `h` nivelety nad terénem – nejlevnější z přípustných variant:

| varianta | přípustná pro | cena za metr |
|---|---|---|
| násyp / zářez | −20 m ≤ h ≤ 15 m, ne nad vodou | objem `|h|·(b + n·|h|)` × Kč/m³ + zábor + demolice |
| estakáda | h ≥ 8 m | Kč/km estakády (+2 %/m nad 20 m) |
| tunel | h ≤ −15 m | Kč/km tunelu |
| most | nad vodou, h ≥ 4 m | Kč/km mostu |

DP najde **globálně nejlevnější** niveletu splňující sklon. Pak se vyhladí (zakružovací oblouky Rv ≈ 0,35·V²),
ve stanicích srovná do vodorovné a znovu se vynutí max. sklon.

## 7. Stavby, demolice, křížení (`structures.py`)
- Každý bod osy se zařadí: v úrovni / násyp / zářez / estakáda / most / tunel / hloubený tunel.
- Úpravy: mezery < 250 m mezi tunely → tunel; mezery < 120 m mezi estakádami → estakáda; tunel kratší než
  minimum → hloubený tunel nebo zářez; estakáda < 60 m → most.
- **Demolice**: budova, jejíž střed leží v záboru tělesa (polovina pláně + svahy + 3 m; estakáda 8 m; tunel nic).
- **Hluk**: budovy do 100 m od osy mimo tunely.
- **Křížení**: průsečíky osy se silnicemi, železnicemi a řekami; v tunelu nebo pod estakádou bez nového objektu.

## 6b. Tunel pod městem, zastávky, podzemní stanice
- V široké zástavbě (kruh o průměru ≥ 800 m, morfologické otevření přes vzdálenostní transformaci) lze nákladovou
  mapu spočítat ve variantě „tunel“: penalizace za vedení městem se nahradí příplatkem za tunel (`tunel_mil_km /
  (svršek + technologie)` ≈ 6). Pro obě varianty se najde koridor a osa, obě se vyhodnotí a vyhraje nižší
  **J = cena + penalizace demolic + hodnota minuty × jízdní doba**.
- Ve výškovém řešení mají povrchové varianty v zástavbě příplatek (vykoupení území), a tunel je tam dovolen už od
  menší hloubky (12 m). Tím se tunel vyplatí i tehdy, když ho nevyžaduje výškový profil.
- **Stanice** (váha 1) a **zastávky** (váha 0,25): nástupiště vodorovně, hloubka pod terénem ≤ 15 m, příplatek
  `podzemní_stanice_mil_m × váha × hloubka`.

## 6c. Paralelní výpočet
Koridory jednotlivých úseků běží souběžně a hledání délkově omezené trasy (λ) se řeší po vlnách (8 + 6 hodnot λ
najednou) v procesech (Dijkstra drží GIL). Zkoušky úseků se sníženou rychlostí a hodnocení variant běží ve vláknech.
Sériový a paralelní výpočet dávají stejný výsledek (stejné vlny λ).

## 7a. Souběh se stávající tratí a silnicemi (`soubeh.py`)
- Volitelně (*Přitahovat trasu k souběhu*, výchozí vypnuto) nákladová mapa: buňky se sledovatelnou
  (dost přímou, R ≥ R_min) stávající kolejí mají cenu ×0,5 a žádné penalizace (zástavba, budovy, chráněná území);
  buňky v pásu silnice (osa ± poloviční šířka vozovky + 10 m; dálnice/silnice pro motorová vozidla 6 m, I. třída
  4 m) ×0,75.
- Rastr 50 m přesnost ±4 m nezachytí, proto se vrcholy koridoru do 1,5 buňky od koleje posunou přesně na kolej.
- Na výsledné ose (po 10 m) se spočítá faktor: vzdálenost ke koleji ≤ 4 m → 0,5 (a žádné demolice), v pásu
  silnice → 0,75. Faktor násobí cenu v dynamickém programování nivelety a v rozpočtu se projeví zápornou
  položkou „Sleva za souběh“ = Σ (1 − faktor) × přímá cena metru (svršek, technologie, zemní práce/objekt, zábor).

## 7b. Úseky se sníženou rychlostí (`omezeni.py`)
Plná rychlost vyžaduje velké oblouky, takže osa někde „řízne“ přes obec či kopec místo optimálního koridoru.
1. **Kandidáti**: okna délky max. 3 km, kde je stavba drahá (cena varianty na metr + demolice nad mediánem)
   a osa se zároveň odchyluje od koridoru víc než 2 buňky rastru.
2. Pro každého kandidáta se osa přepočítá s menším minimálním poloměrem jen v okně – pro 120 km/h
   R = 11,8·120²/(D+I) ≈ 700 m a pro střední rychlost – a celá varianta se znovu vyhodnotí
   (niveleta, stavby, rozpočet, jízdní doba).
3. Přijme se, pokud kritérium J = cena + penalizace·demolice klesne, nepřibude žádná demolice a úspora je
   ≥ 300 mil. Kč nebo ≥ 5 domů.
   Vyšší rychlost má přednost, dá-li ≥ 80 % úspory. Vybere se max. 4 nepřekrývajících se úseků a ověří
   jejich společný účinek.

Demolice se v optimalizaci (koridor, niveleta, klasifikace, výběr úseků) počítají s **penalizací +40 mil. Kč/dům**
navíc k ceně výkupu; rozpočet obsahuje jen skutečnou cenu výkupu.

## 7c. Ruční limity rychlosti úseků a porovnání s autem
`Bod.max_rychlost_kmh` je limit úseku od bodu k dalšímu bodu. V `horizontal.fit_alignment(rmin_useky=…)` dostane
každý vrchol (podle nejbližšího koridoru) nejmenší poloměr `NavrhoveParametry.min_polomer_pro(v)` svého úseku; v
`traction.speed_limit(limity=…)` se rychlost v úseku omezí na limit (minimum se rozšíří o délku vlaku jako u oblouků).
Limity se předávají i do přepočtu vlak × linka. `auto.py` zjišťuje dobu jízdy autem mezi stanicemi (Mapy.cz routing,
záložně OSRM; cache na disku) a `report.tab_auto` ji porovná s jízdním řádem.

## 8. Rozpočet a jízdní doby
- **Rozpočet** (`costs.py`): délky × jednotkové ceny + kubatury + portály + křížení + stanice + demolice +
  pozemky, k tomu projekce (10 %) a rezerva (20 %).
- **Jízdní doby** (`traction.py`): simulace po 10 m. Rychlostní limit = min(návrhová rychlost, rychlost v oblouku
  `v = √(R·(D+I)/11,8)`, zastavení ve stanicích), rozšířený o délku vlaku. Dopředný průchod = rozjezd
  (tažná síla `min(F_max, P/v)` − Davisův odpor − sklon), zpětný průchod = brzdění. Přičte se rezerva a pobyty (90 s).
- **Linky**: simulace zastavuje jen ve stanicích linky (+ konce); projížděné stanice mají čas průjezdu.
  Matice vlak × linka se počítá pro všechny předvolby vlaků.
- **Vlaky**: předvolby RegioPanter (160 km/h, 2,0 MW, 156 t), Railjet (230 km/h, 6,4 MW, 440 t), Pendolino
  (230 km/h, 4 MW, 385 t, naklápění → nedostatek převýšení 270 mm), ICE 3 (320 km/h, 8 MW, 435 t), TGV
  Euroduplex (320 km/h, 9,3 MW, 424 t). Rychlost vlaku = min(traťová, max. vlaku); jízdní doby se počítají pro
  všechny předvolby (porovnání).
