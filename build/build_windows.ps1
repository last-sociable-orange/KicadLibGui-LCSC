# Build the one-file Windows executable for KiCad LibGen LCSC.
#
#   .\build\build_windows.ps1
#
# Produces dist\KiCadLibGenLCSC.exe plus a SHA256 file.  PyInstaller cannot
# cross-compile: run this on Windows, and build_linux.sh on Linux.

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

$python = if (Test-Path ".venv\Scripts\python.exe") { ".venv\Scripts\python.exe" } else { "python" }
Write-Host "Using interpreter: $python"

Write-Host "== version =="
& $python gui_main.py --version

Write-Host "== tests =="
& $python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "tests failed" }

Write-Host "== lint =="
& $python -m ruff check .
if ($LASTEXITCODE -ne 0) { throw "lint failed" }

Write-Host "== self-test =="
& $python gui_main.py --self-test
if ($LASTEXITCODE -ne 0) { throw "self-test failed" }

Write-Host "== pyinstaller =="
& $python -m PyInstaller --clean --noconfirm build\kicad_lib_gen_lcsc.spec
if ($LASTEXITCODE -ne 0) { throw "build failed" }

$exe = Join-Path (Get-Location) "dist\KiCadLibGenLCSC.exe"
if (-not (Test-Path $exe)) { throw "expected $exe" }

$size = [math]::Round((Get-Item $exe).Length / 1MB, 1)
$hash = (Get-FileHash $exe -Algorithm SHA256).Hash.ToLower()
"$hash  KiCadLibGenLCSC.exe" | Set-Content "dist\KiCadLibGenLCSC.exe.sha256" -Encoding ascii

Write-Host ""
Write-Host ("Built {0} ({1} MB)" -f $exe, $size)
Write-Host "SHA256 $hash"

Write-Host "== packaged self-test =="
& $exe --self-test
