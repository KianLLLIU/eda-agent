# ===========================================================================
#  EDA Agent - One-click desktop build (Windows / PowerShell 5.1+)
#
#  Usage (from project root):
#     powershell -ExecutionPolicy Bypass -File scripts\build_desktop.ps1
#  Optional:
#     -Python "C:\Path\To\python.exe"   use a specific interpreter
#     -SkipInstaller                    build portable exe only
#
#  Outputs:
#     dist\EDA-Agent.exe                         portable, double-click to run
#     dist\installer\EDA-Agent-Setup-v2.0.2.exe  real installer (if ISCC found)
# ===========================================================================

param(
    [string]$Python = "python",
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

function Invoke-Checked {
    param([string]$Label, [scriptblock]$Action)
    Write-Host ""
    Write-Host "==> $Label" -ForegroundColor Cyan
    & $Action
    if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne $null) {
        throw "Step failed: $Label (exit code $LASTEXITCODE)"
    }
}

Write-Host "============================================================"
Write-Host "  EDA Agent Desktop Build"
Write-Host "  Root: $root"
Write-Host "  Python: $Python"
Write-Host "============================================================"

# 1. Runtime dependencies
Invoke-Checked "Install runtime dependencies" {
    & $Python -m pip install -r requirements.txt -q
}
Invoke-Checked "Install Pillow (icon generator)" {
    & $Python -m pip install pillow -q
}
Invoke-Checked "Install PyInstaller" {
    & $Python -m pip install pyinstaller -q
}

# 2. Native window support is optional: if it fails, the app falls back to browser.
Write-Host ""
Write-Host "==> Install pywebview (optional native window)" -ForegroundColor Cyan
& $Python -m pip install pywebview pythonnet -q 2>$null
if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne $null) {
    Write-Host "    [WARN] pywebview not installed - app will use browser fallback." -ForegroundColor Yellow
} else {
    Write-Host "    pywebview ready (native window enabled)."
}

# 3. Icon
Invoke-Checked "Generate application icon" {
    & $Python scripts/make_icon.py
}

# 4. PyInstaller one-file GUI build
Invoke-Checked "Build portable executable" {
    & $Python -m PyInstaller --clean -y packaging/eda_agent_desktop.spec
}
$exe = Join-Path $root "dist\EDA-Agent.exe"
if (-not (Test-Path $exe)) { throw "Build finished but dist\EDA-Agent.exe was not found." }
$exeInfo = Get-Item $exe
Write-Host ("    dist\EDA-Agent.exe  ({0:N1} MB)" -f ($exeInfo.Length / 1MB)) -ForegroundColor Green

# 5. Inno Setup installer (optional)
if ($SkipInstaller) {
    Write-Host ""
    Write-Host "==> Skipping installer (-SkipInstaller)." -ForegroundColor Yellow
} else {
    $iscc = $null
    $candidates = @(
        (Get-Command "ISCC.exe" -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue),
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        "C:\Program Files\Inno Setup 6\ISCC.exe",
        "C:\Program Files (x86)\Inno Setup 5\ISCC.exe"
    )
    foreach ($c in $candidates) {
        if ($c -and (Test-Path $c)) { $iscc = $c; break }
    }
    if ($iscc) {
        New-Item -ItemType Directory -Force -Path (Join-Path $root "dist\installer") | Out-Null
        Write-Host ""
        Write-Host "==> Compile Inno Setup installer" -ForegroundColor Cyan
        & $iscc "$root\installer\EDA-Agent.iss"
        if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne $null) {
            Write-Host "    [WARN] ISCC failed; portable exe is still usable." -ForegroundColor Yellow
        } else {
            Get-ChildItem (Join-Path $root "dist\installer") -Filter "*.exe" | ForEach-Object {
                Write-Host ("    dist\installer\{0}  ({1:N1} MB)" -f $_.Name, ($_.Length / 1MB)) -ForegroundColor Green
            }
        }
    } else {
        Write-Host ""
        Write-Host "    [INFO] Inno Setup (ISCC.exe) not found - skipped installer." -ForegroundColor Yellow
        Write-Host "           Install Inno Setup 6 and re-run, or ship dist\EDA-Agent.exe directly."
    }
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  DONE. Double-click dist\EDA-Agent.exe to launch." -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
