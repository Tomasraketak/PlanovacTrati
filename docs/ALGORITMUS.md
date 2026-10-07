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
- **OpenStreetMap** (Overpass API): zástavba (landuse), obce, vodní plochy a řeky, silnice I./II. třídy, dálnice,
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

## 7b. Úseky se sníženou rychlostí (`omezeni.py`)
Plná rychlost vyžaduje velké oblouky, takže osa někde „řízne“ přes obec či kopec místo optimálního koridoru.
1. **Kandidáti**: okna délky max. 3 km, kde je stavba drahá (cena varianty na metr + demolice nad mediánem)
   a osa se zároveň odchyluje od koridoru víc než 2 buňky rastru.
2. Pro každého kandidáta se osa přepočítá s menším minimálním poloměrem jen v okně – pro 120 km/h
   R = 11,8·120²/(D+I) ≈ 700 m a pro střední rychlost – a celá varianta se znovu vyhodnotí
   (niveleta, stavby, rozpočet, jízdní doba).
3. Přijme se, pokud kritérium J = cena + penalizace·demolice klesne a úspora ≥ 300 mil. Kč nebo ≥ 5 domů.
   Vyšší rychlost má přednost, dá-li ≥ 80 % úspory. Vybere se max. 4 nepřekrývajících se úseků a ověří
   jejich společný účinek.

Demolice se v optimalizaci (koridor, niveleta, klasifikace, výběr úseků) počítají s **penalizací +40 mil. Kč/dům**
navíc k ceně výkupu; rozpočet obsahuje jen skutečnou cenu výkupu.

## 8. Rozpočet a jízdní doby
- **Rozpočet** (`costs.py`): délky × jednotkové ceny + kubatury + portály + křížení + stanice + demolice +
  pozemky, k tomu projekce (10 %) a rezerva (20 %).
- **Jízdní doby** (`traction.py`): simulace po 10 m. Rychlostní limit = min(návrhová rychlost, rychlost v oblouku
  `v = √(R·(D+I)/11,8)`, zastavení ve stanicích), rozšířený o délku vlaku. Dopředný průchod = rozjezd
  (tažná síla `min(F_max, P/v)` − Davisův odpor − sklon), zpětný průchod = brzdění. Přičte se rezerva a pobyty (90 s).
- **Vlaky**: předvolby RegioPanter (160 km/h, 2,0 MW, 156 t), Railjet (230 km/h, 6,4 MW, 440 t), Pendolino
  (230 km/h, 4 MW, 385 t, naklápění → nedostatek převýšení 270 mm), ICE 3 (320 km/h, 8 MW, 435 t), TGV
  Euroduplex (320 km/h, 9,3 MW, 424 t). Rychlost vlaku = min(traťová, max. vlaku); jízdní doby se počítají pro
  všechny předvolby (porovnání).
