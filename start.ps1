# ===== Planovac trati - instalace / aktualizace / spusteni jednim prikazem (Windows PowerShell 5.1+) =====
# Pouziti (v cistem terminalu):
#   powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/Tomasraketak/PlanovacTrati/HEAD/start.ps1 | iex"
# Nastaveni pres promenne prostredi (nepovinne):
#   PLANOVAC_DIR                 cilova slozka (vychozi %USERPROFILE%\PlanovacTrati, nebo slozka tohoto skriptu)
#   PLANOVAC_BEZ_AKTUALIZACE=1   nestahovat novou verzi, jen spustit
#   PLANOVAC_BRANCH              vetev (vychozi vychozi vetev repozitare)
$ErrorActionPreference = 'Continue'   # nativni prikazy (git, pip) pisou do stderr - kontrolujeme jen navratove kody
$Repo = 'https://github.com/Tomasraketak/PlanovacTrati'

function Zprava($t) { Write-Host "[Planovac] $t" -ForegroundColor Cyan }
function Chyba($t) { Write-Host "[Planovac] CHYBA: $t" -ForegroundColor Red }

function Obnov-Cestu {
    $m = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $u = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = "$m;$u"
}

function Najdi-Python {
    foreach ($c in @(@('py', '-3'), @('python'), @('python3'))) {
        $exe = $c[0]
        if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
        $arg = @(); if ($c.Length -gt 1) { $arg = $c[1..($c.Length - 1)] }
        try {
            & $exe @arg -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>$null
            if ($LASTEXITCODE -eq 0) { return ,(@($exe) + $arg) }
        } catch { }
    }
    return $null
}

function Winget-Instaluj($id, $nazev) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { return $false }
    Zprava "Instaluji $nazev (winget) ..."
    winget install -e --id $id --accept-package-agreements --accept-source-agreements --silent
    Obnov-Cestu
    return $true
}

# ---------------------------------------------------------------- slozka
if ($env:PLANOVAC_DIR) { $Slozka = $env:PLANOVAC_DIR }
elseif ($PSScriptRoot -and (Test-Path (Join-Path $PSScriptRoot 'app.py'))) { $Slozka = $PSScriptRoot }
else { $Slozka = Join-Path $env:USERPROFILE 'PlanovacTrati' }
$BezAkt = [bool]$env:PLANOVAC_BEZ_AKTUALIZACE

# ---------------------------------------------------------------- Python
$py = Najdi-Python
if (-not $py) {
    Winget-Instaluj 'Python.Python.3.12' 'Python 3.12' | Out-Null
    $py = Najdi-Python
}
if (-not $py) {
    Chyba 'Python 3.10 nebo novejsi nebyl nalezen. Nainstalujte jej z https://www.python.org/downloads/ (zaskrtnete Add python.exe to PATH) a spustte prikaz znovu.'
    exit 1
}

# ---------------------------------------------------------------- zdrojove soubory (git / ZIP)
function Stahni-Zip {
    Zprava 'Git neni dostupny - stahuji ZIP z GitHubu ...'
    $vetev = if ($env:PLANOVAC_BRANCH) { $env:PLANOVAC_BRANCH } else { 'HEAD' }
    $tmp = Join-Path $env:TEMP ('planovac_' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $tmp | Out-Null
    $zip = Join-Path $tmp 'src.zip'
    Invoke-WebRequest -UseBasicParsing -Uri "$Repo/archive/$vetev.zip" -OutFile $zip
    Expand-Archive -Path $zip -DestinationPath $tmp -Force
    $src = Get-ChildItem $tmp -Directory | Select-Object -First 1
    New-Item -ItemType Directory -Force -Path $Slozka | Out-Null
    foreach ($it in Get-ChildItem $src.FullName -Force) {
        if ($it.Name -in @('.venv', 'data', 'vystupy')) { continue }
        if ($it.Name -eq 'projekty' -and (Test-Path (Join-Path $Slozka 'projekty'))) {
            Copy-Item (Join-Path $it.FullName '*') (Join-Path $Slozka 'projekty') -Recurse -Force -ErrorAction SilentlyContinue
            continue
        }
        Copy-Item $it.FullName $Slozka -Recurse -Force
    }
    Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
}

function Aktualizuj-Zdroj {
    $git = Get-Command git -ErrorAction SilentlyContinue
    if (-not $git -and -not (Test-Path (Join-Path $Slozka '.git'))) {
        Winget-Instaluj 'Git.Git' 'Git' | Out-Null
        $git = Get-Command git -ErrorAction SilentlyContinue
    }
    if (Test-Path (Join-Path $Slozka '.git')) {
        if ($git -and -not $BezAkt) {
            Zprava 'Aktualizuji program (git pull) ...'
            Push-Location $Slozka
            try {
                if ($env:PLANOVAC_BRANCH) { git fetch origin $env:PLANOVAC_BRANCH; git checkout $env:PLANOVAC_BRANCH }
                git pull --ff-only
                if ($LASTEXITCODE -ne 0) { Write-Host '[Planovac] Aktualizace se nepodarila (mate lokalni zmeny?) - spoustim stavajici verzi.' -ForegroundColor Yellow }
            } finally { Pop-Location }
        }
    } elseif (-not (Test-Path (Join-Path $Slozka 'app.py'))) {
        if ($git) {
            Zprava "Stahuji program do $Slozka ..."
            if ($env:PLANOVAC_BRANCH) { git clone --branch $env:PLANOVAC_BRANCH $Repo $Slozka } else { git clone $Repo $Slozka }
            if ($LASTEXITCODE -ne 0) { Stahni-Zip }
        } else { Stahni-Zip }
    } elseif (-not $BezAkt -and -not $git) {
        Stahni-Zip
    }
    if (-not (Test-Path (Join-Path $Slozka 'app.py'))) { Chyba "Program se nepodarilo ziskat do $Slozka."; exit 1 }
}

Aktualizuj-Zdroj
Set-Location $Slozka

# ---------------------------------------------------------------- virtualni prostredi + knihovny
$venvPy = Join-Path $Slozka '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPy)) {
    Zprava 'Vytvarim virtualni prostredi .venv ...'
    $arg = @(); if ($py.Length -gt 1) { $arg = $py[1..($py.Length - 1)] }
    & $py[0] @arg -m venv .venv
    if ($LASTEXITCODE -ne 0) { Chyba 'Nepodarilo se vytvorit virtualni prostredi.'; exit 1 }
}
$hashFile = Join-Path $Slozka '.venv\requirements.sha'
$hash = (Get-FileHash (Join-Path $Slozka 'requirements.txt') -Algorithm SHA256).Hash
$stary = if (Test-Path $hashFile) { (Get-Content $hashFile -Raw).Trim() } else { '' }
if ($hash -ne $stary) {
    Zprava 'Instaluji / aktualizuji knihovny (pri prvnim spusteni nekolik minut) ...'
    & $venvPy -m pip install --upgrade pip --quiet
    & $venvPy -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { Chyba 'Instalace knihoven selhala. Zkontrolujte pripojeni k internetu a spustte prikaz znovu.'; exit 1 }
    Set-Content -Path $hashFile -Value $hash
}

# ---------------------------------------------------------------- spusteni (kod 75 = zadost o restart z GUI)
$env:PLANOVAC_LAUNCHER = '1'
do {
    Zprava 'Spoustim Planovac trati ... (okno prohlizece se otevre samo; ukonceni: Ctrl+C nebo tlacitko v aplikaci)'
    & $venvPy -m streamlit run app.py --browser.gatherUsageStats false
    $kod = $LASTEXITCODE
    if ($kod -eq 75) { Zprava 'Restartuji aplikaci ...' }
} while ($kod -eq 75)
