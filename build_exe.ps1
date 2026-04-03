Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

python -m pip install --upgrade pip | Out-Host
python -m pip install -r requirements.txt | Out-Host
python -m pip install --upgrade pyinstaller | Out-Host

pyinstaller --noconfirm --clean DelTA.spec | Out-Host

Write-Host ""
Write-Host "Done. Output:"
Write-Host "  dist\DelTA\DelTA.exe"

