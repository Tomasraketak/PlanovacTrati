# 📖 Návod k použití

## Rychlý start (3 kroky)

1. **Zadejte body trasy** na kartě *🗺️ Trasa a zastávky* – klikněte do mapy, vyplňte název, zvolte typ
   a stiskněte **➕ Přidat bod**. Nebo použijte hledání podle názvu, případně upravte tabulku přímo.
2. **Nastavte parametry** v levém panelu – rychlost, max. sklon, max. prodloužení a priority.
3. Stiskněte **🚀 Navrhnout trať**. Průběh uvidíte nahoře; výsledky najdete na dalších kartách.

> 💡 Poprvé zkuste projekt **demo** (levý panel → *📁 Projekt* → *demo* → *Načíst projekt*). Počítá se
> na vygenerované krajině, nic se nestahuje a je hotový za pár sekund.

## Body trasy

| Typ | Význam |
|---|---|
| 🚉 **stanice** | vlak zde zastavuje; trať je zde přímá a vodorovná v délce nástupiště; zástavba v okolí (výchozí 2 km) se nepenalizuje, takže trať může vést do města |
| ◆ **průjezdní bod** | trasa musí projít tímto místem (např. koridor podél dálnice, překonání údolí na určitém místě), vlak nezastavuje |

- Pořadí bodů = pořadí jízdy. První a poslední bod musí být stanice.
- Řádky v tabulce lze mazat (zaškrtnout vlevo a klávesa Delete / ikona koše) i přidávat (řádek dole).
- **⇅ Obrátit směr** otočí celou trasu. **↕ Posunout poslední výš** pomůže, když nově přidaný bod patří doprostřed.
- Při přidávání bodu z mapy lze rovnou vybrat, *před který bod* se má vložit.

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
