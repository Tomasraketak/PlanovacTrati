# 📖 Návod k použití

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

### 🐢 Úseky se sníženou rychlostí
Program smí na celé trati použít nejvýše **4 úseky** (nastavitelné), každý nejvýše **3 km** dlouhý, kde vlak
pojede pomaleji (nejméně **120 km/h**). V takovém úseku smí být menší oblouky, takže se trať může vyhnout
vesnici, kopci nebo údolí. Úsek se použije jen tehdy, když **ušetří alespoň 300 mil. Kč** nebo **zachrání
alespoň 5 domů** (obojí nastavitelné) – a nikdy nesmí počet demolic zvýšit. Na kartě *🏗️ Stavby* je tabulka použitých úseků i protokol, co všechno
program zkoušel; v mapě jsou žlutě, v grafu rychlosti jako žluté pásy.

### 🚆 Vlak
Vyberte vlak: **RegioPanter (ČD 640)**, **Railjet**, **Pendolino (ČD 680, naklápěcí – rychleji v obloucích)**,
**ICE 3**, **TGV Euroduplex**, nebo *vlastní*. Předvolby mají orientační reálné parametry (výkon, hmotnost,
tažná síla, zrychlení, brzdění, jízdní odpory); lze je upravit v *Parametry vozidla*. Pobyt v každé zastávce je
výchozích **90 s**. Po výpočtu ukazuje karta *⏱️ Jízdní doby* **porovnání všech vlaků** a jízdní řád pro kterýkoli
z nich – bez nutnosti přepočítávat trať.

### 🖥️ Výpočet a data
- **Rozlišení rastru**: 100 m = rychlý náhled, **50 m = doporučeno**, 25 m = detail (pomalejší, víc paměti).
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
- Overpass API (OSM) je občas přetížené – program to zkouší opakovaně a na více serverech. Když se vrstvu
  nepodaří stáhnout, zobrazí varování; stačí výpočet za chvíli zopakovat (stažená data zůstávají v cache).

## Příkazová řádka

```bat
planovac.bat run projekty\cb_jh_jihlava.yaml
planovac.bat run projekty\demo.yaml --rozliseni 100 -o vystupy\demo
planovac.bat novy projekty\moje_trat.yaml
```
Výstupy (report, mapa, GeoJSON, KML, CSV, souhrn) se uloží do složky `vystupy\…`.
