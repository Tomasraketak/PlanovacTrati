# 📖 Návod k použití

## Instalace, aktualizace, spuštění
Celé je to jeden příkaz z README (`start.ps1` / `start.sh`). V aplikaci pak levý panel **⚙️ Aplikace** umí zkontrolovat
a nainstalovat aktualizace, restartovat či ukončit program a smazat stažená data.

## Rychlý start (3 kroky)

1. **Naklikejte body trasy** na kartě *🗺️ Trasa a zastávky* – nad mapou zvolte režim **🚉 Stanice** nebo
   **◆ Průjezdní bod** a klikejte do mapy. Každý klik rovnou přidá bod, sám ho zařadí do pořadí a pojmenuje.
   a stiskněte **➕ Přidat bod**. Nebo použijte hledání podle názvu, případně upravte tabulku přímo.
2. **Nastavte parametry** v levém panelu – rychlost, max. sklon, max. prodloužení a priority.
3. Stiskněte **🚀 Navrhnout trať**. Průběh uvidíte nahoře; výsledky najdete na dalších kartách.

> 💡 Poprvé zkuste projekt **demo** (levý panel → *📁 Projekt* → *demo* → *Načíst projekt*). Počítá se
> na vygenerované krajině, nic se nestahuje a je hotový za pár sekund.

## Body trasy

| Typ | Význam |
|---|---|
| 🔵 **stanice** | vlak zde zastavuje; trať je zde přímá a vodorovná v délce nástupiště; zástavba v okolí (výchozí 2 km) se nepenalizuje, takže trať může vést do města |
| 🔶 **průjezdní bod** | trasa musí projít tímto místem (např. koridor podél dálnice, překonání údolí na určitém místě, obejití obce zvolenou stranou), vlak nezastavuje |

### Klikání do mapy
- **Režim nad mapou**: *🚉 Stanice* / *◆ Průjezdní bod* – každý klik do mapy přidá bod daného typu.
  Program ho **sám vloží do pořadí** tam, kde nejméně prodlouží trasu (průjezdní bod mezi Třeboní a
  Jindřichovým Hradcem se tedy zařadí mezi ně), a **pojmenuje ho podle nejbližší obce**.
- **✋ Vybrat bod** (nebo kdykoli klik na značku): vpravo se ukáže panel – přejmenovat, přepnout stanice ↔
  průjezdní bod, **📍 Přesunout** (další klik do mapy bod přesune), **⬆️/⬇️** změnit pořadí, **🗑️ Smazat**.
- **↩️ Zpět** vrátí poslední změnu bodů.
- Body lze přidat i z **vyhledávání podle názvu** (tlačítka „Přidat jako stanici / jako průjezdní bod“) nebo
  upravit přímo v tabulce pod mapou. První a poslední bod musí být stanice.

## Parametry

### ⚙️ Návrhové parametry
- **Návrhová rychlost** – určuje min. poloměr oblouků (R = 11,8·V²/(D+I)) a jízdní doby.
- **Max. podélný sklon** – VRT pouze pro osobní dopravu běžně 25–35 ‰; s nákladní dopravou 12,5–18 ‰.
  Menší sklon = více tunelů a estakád.
- **Max. prodloužení proti vzdušné čáře** – kolik % smí být každý úsek mezi sousedními body delší než
  vzdušná čára. Malá hodnota = přímější, ale dražší trasa.
- *Pokročilé*: sklon ve stanici, délka nástupiště, převýšení, limity násypů/zářezů, od kdy estakáda a tunel,
  okruh kolem stanic bez penalizace zástavby.

### ⚖️ Priority optimalizace
Posuvníky 0–5 (1 = výchozí). **Penalizace zbourání domu** (výchozí 40 mil. Kč/dům) se přičítá k ceně
výkupu jen při hledání trasy – trať tak raději zaplatí delší estakádu, tunel či oblouk, než aby bourala. Do
rozpočtu se nezapočítává. Např. chcete-li **co nejméně tunelů a estakád**, zvyšte *⛰️ Šetřit tunely…*;
chcete-li **nebourat domy**, zvyšte *🏠 Nebourat domy* a *🏘️ Vyhýbat se obcím*. *📏 Co nejkratší trasa* tlačí
na přímost.

### 💰 Jednotkové ceny
Všechny ceny jsou editovatelné (mil. Kč za km / kus, Kč za m³ / m²). Výchozí hodnoty odpovídají řádově
cenové úrovni ČR ~2025.

### 🎛️ Karta Koeficienty
Všechny ceny, váhy a penalizace jsou na jedné kartě: hodnota minuty jízdní doby, penalizace demolic, tunel pod
městem, podzemní stanice, malé zastávky, ceny staveb, souběh, úseky se sníženou rychlostí a koeficienty
nákladové mapy (zástavba, budovy, terén, voda, chráněná území). *Obnovit výchozí* vrátí původní hodnoty.

### 🏙️ Tunel pod městem
Kde město stojí v cestě, program porovná dvě varianty: **obchvat** (trasa město objede, je delší a pomalejší)
a **tunel** (pod zástavbou, dražší). Rozhoduje součet *cena + penalizace demolic + hodnota minuty × jízdní doba*
(výchozí 500 mil. Kč za minutu). Tunel se zvažuje jen pod dostatečně velkou zástavbou (≥ 800 m) – kratší nevyjde
kvůli rampám při daném sklonu. Orientační doba výstavby tunelu se jen zobrazí, do rozhodování nevstupuje.

### 🚏 Zastávky a podzemní stanice
- **Zastávka** je malá stanice (kratší nástupiště, levnější) – typicky ji obsluhují jen zastávkové vlaky;
  rychlík a expres v ní nestaví (nastavuje se v *Linky*).
- **Stanice i zastávky smí být až 15 m pod terénem** (nastavitelné); každý metr hloubky se připlácí. Program
  stanici zahloubí sám, pokud je to levnější než násyp nebo estakáda (např. pod městem).

### 🛤️ Souběh se stávající tratí a silnicí
- Kde osa nové trati vede **do ±4 m od stávající koleje**, využije se stávající těleso a pozemky: stavba je
  **o 50 % levnější** a v tom místě se nepočítají penalizace za zástavbu, domy ani chráněná území (nic se nebourá).
  Program vrcholy trasy ležící blízko koleje „přichytí“ přímo na ni, takže na přímých úsecích stávající trati
  vede nová osa přesně po ní.
- Kde osa vede **do 10 m od okraje dálnice, silnice pro motorová vozidla nebo silnice I. třídy**, je stavba
  **o 25 % levnější** (společný koridor).
- Sleva se počítá vždy přesně na výsledné ose a ovlivňuje i výškové řešení. Volba *Přitahovat trasu k souběhu*
  zvýhodní stávající přímé tratě a silnice už při hledání koridoru – rastr 50 m ale přesný souběh nezaručí, proto je
  ve výchozím stavu vypnutá (vyplatí se porovnat obě varianty).
- Všechny hodnoty jsou nastavitelné. V mapě je souběh zeleně (trať) a tmavě šedě (silnice), sleva je v rozpočtu
  jako samostatná položka a na kartě *🏗️ Stavby* je seznam úseků souběhu.

### 🚉 Linky – kde vlaky zastavují
Linka určuje, ve kterých stanicích vlak zastaví (první a poslední vždy). Výchozí jsou **zastávkový** (všechny
stanice), **expres** (bez zastavení) a **rychlík** (vybrané stanice). Linky lze přidávat, přejmenovávat a měnit
jim zastávky; karta *⏱️ Jízdní doby* pak ukazuje **tabulku vlak × linka** a jízdní řád pro zvolenou kombinaci
(projížděné stanice s časem průjezdu) – bez nového návrhu trati.

### 🐢 Pravidla pro úseky se sníženou rychlostí
Optimalizace smí na krátkých úsecích **snížit rychlost** (menší oblouky), takže se trať může vyhnout vesnici, kopci
nebo údolí. Co přesně smí, určuje **tabulka pravidel** (karta *🎛️ Koeficienty* → *Úseky se sníženou rychlostí*;
řádky lze přidávat, mazat a vypínat):

| Sloupec | Význam |
|---|---|
| Max. délka [m] | nejdelší úsek, na kterém smí pravidlo snížit rychlost |
| Nejnižší rychlost [km/h] | nejnižší rychlost v úseku (80 km/h → oblouky od R ≈ 300 m, 120 km/h → R ≈ 700 m) |
| Max. počet | kolikrát smí být pravidlo na trati použito |
| Úspora ≥ [mil. Kč] / zachrání ≥ [domů] | úsek se použije jen tehdy, když ušetří aspoň tolik peněz **nebo** zachrání aspoň tolik domů |

Výchozí jsou dvě pravidla: **mírné** (do 3 km, ≥ 120 km/h, 4×, při úspoře ≥ 300 mil. Kč nebo ≥ 5 domech) a **silné**
(do 2 km, až 80 km/h, 2×, jen při úspoře ≥ 500 mil. Kč nebo ≥ 10 domech). Nad tím je celkový limit počtu úseků.
Žádné pravidlo nikdy nesmí počet demolic zvýšit a úsek se musí vyplatit i po započtení ztraceného času
(hodnota minuty). Tabulka použitých úseků a protokol zkoušek je na kartě *🏗️ Stavby*; v mapě jsou žlutě, v grafu
rychlosti jako žluté pásy.

### 🐇 Limit rychlosti po úsecích
V tabulce bodů (karta *Trasa a zastávky*) je sloupec **Max. rychlost k dalšímu bodu [km/h]** (nebo pole ve
panelu vybraného bodu). Limit platí v úseku od daného bodu k následujícímu – mezi libovolnými stanicemi,
zastávkami i průjezdními body; prázdné pole = platí globální návrhová rychlost. Limit (a) omezí rychlost vlaku
a prodlouží jízdní dobu, (b) v daném úseku **zmenší nejmenší povolený poloměr oblouků** (R = 11,8·V²/(D+I)), takže
trasa smí být přímější a levnější, a (c) je v grafu rychlosti šedým pásem a v souhrnu. Limit patří bodu – při
změně pořadí bodů se přesouvá s ním.

### 🚗 Porovnání s autem
Na kartě *⏱️ Jízdní doby* tlačítko **🚗 Načíst** zjistí dobu jízdy autem mezi stanicemi a porovná ji s vlakem
(zvolený vlak a linka): vzdálenost po trati a po silnici, časy, rozdíl v minutách, poměr a průměrné rychlosti,
včetně řádku CELKEM a grafu. Zdroj: **Mapy.cz** routing API (API klíč zdarma na <https://developer.mapy.com>,
zadejte v poli *Mapy.cz API klíč* – uloží se trvale jen na vašem počítači (`~/.planovac/nastaveni.json`, tj. `%USERPROFILE%\\.planovac`), přežije aktualizaci a nepřidává se do repozitáře; nebo proměnná prostředí `MAPY_API_KEY`); bez klíče nebo při
chybě se použije **OSRM** (veřejné, bez dopravní situace). Z příkazové řádky: `planovac.bat run projekt.yaml --auto`.
Časy autem jsou orientační (bez zácp, semaforů mimo to, co ví služba).

### 🚆 Vlak
Vyberte vlak: **RegioPanter (ČD 640)**, **Railjet**, **ComfortJet (Škoda 109E + vozy, 200 km/h)**, **Pendolino (ČD 680, naklápěcí – rychleji v obloucích)**,
**ICE 3**, **TGV Euroduplex**, nebo *vlastní*. Předvolby mají orientační reálné parametry (výkon, hmotnost,
tažná síla, zrychlení, brzdění, jízdní odpory); lze je upravit v *Parametry vozidla*. Pobyt v každé zastávce je
výchozích **90 s**. Po výpočtu ukazuje karta *⏱️ Jízdní doby* **porovnání všech vlaků** a jízdní řád pro kterýkoli
z nich – bez nutnosti přepočítávat trať.

### 🖥️ Výpočet a data
- **Rozlišení rastru**: 100 m = rychlý náhled, 50 m = rychlé, **20 m = doporučeno** (detail), 10–15 m jen s velkou RAM.
  Pod volbou je odhad počtu buněk a paměti. Výpočet běží na všech jádrech (*Počet vláken*). Zdrojový výškový
  model má 30 m, takže 20 m zpřesňuje hlavně polohu osy a obcházení zástavby; skutečný detail terénu dá vlastní DMR 5G.
- **Demo režim**: syntetický terén bez internetu.
- **Stahovat budovy v celé oblasti**: standardně vypnuto – program nejdřív najde trasu podle zástavby, pak stáhne
  budovy v pásu 1,2 km kolem ní a návrh zopakuje už s ohledem na jednotlivé domy. Zapnutí stáhne budovy v celé
  oblasti (u velkých oblastí trvá desítky minut kvůli limitům Overpass API).
- **Vlastní DEM**: cesta k GeoTIFF s přesnějším výškovým modelem (např. DMR 5G od ČÚZK).

## Výsledky

| Karta | Co obsahuje |
|---|---|
| 🚄 Výsledek | hlavní čísla (délka, cena, jízdní doba, tunely, estakády, demolice) a interaktivní mapa |
| 📈 Profil a rychlost | podélný profil s barevnými úseky, sklony, rychlostní profil vlaku |
| 🏗️ Stavby | souhrn a seznam tunelů/estakád/mostů, křížení, oblouky, obce u trati, chráněná území |
| 💰 Rozpočet | položkový rozpočet a graf |
| ⏱️ Jízdní doby | jízdní řád, úseky, průměrné rychlosti |
| ⬇️ Export | HTML report, GeoJSON, KML, CSV, YAML, ZIP |

**V mapě** lze vpravo nahoře přepínat podklady (OSM, topografická, satelit) a vrstvy (jednotlivé typy staveb,
demolice, kilometrovník, koridor před vložením oblouků, **nákladová mapa** – ukazuje, kde je stavba drahá).
Najetím myší na úsek trati se zobrazí jeho typ, staničení a délka. Vlevo je měření vzdáleností a celá obrazovka.

## Tipy

- Trasa vede jinudy, než chcete? Přidejte **průjezdní bod**.
- Hodně tunelů? Zvyšte max. sklon nebo povolené prodloužení, případně váhu *Šetřit tunely*.
- Trasa prochází vesnicí? Zvyšte váhu *Vyhýbat se obcím* (a zkontrolujte, že tam není zbytečně stanice).
- Porovnání variant: uložte projekt pod různými jmény a porovnejte HTML reporty.
- **Zdroje dat:** Overpass API (OSM) je občas přetížené – program to zkouší opakovaně na více serverech a pak
  (volba *Výpočet a data → Zdroj dat = Automaticky*) použije **Overture Maps** (budovy, silnice, železnice, voda,
  zástavba, sídla; čte se po částech z parquet souborů na S3, první použití vrstvy vytváří index a trvá déle,
  výsledky se ukládají do `data/cache`). Chráněná území má jen OSM. Zdroj každé vrstvy je v souhrnu výsledku.
  Režimy *Jen Overpass* / *Jen Overture* jsou pro porovnání. Když se vrstvu
  nepodaří stáhnout, zobrazí varování; stačí výpočet za chvíli zopakovat (stažená data zůstávají v cache).

## Příkazová řádka

```bat
planovac.bat run projekty\demo.yaml
planovac.bat run projekty\demo.yaml --rozliseni 100 -o vystupy\demo
planovac.bat novy projekty\moje_trat.yaml
```
Výstupy (report, mapa, GeoJSON, KML, CSV, souhrn) se uloží do složky `vystupy\…`.
