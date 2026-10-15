# Re-run the rules evaluation only (no reinstall, docs are NOT regenerated so before/after use the same files).
#   powershell -ExecutionPolicy Bypass -File .\run_eval.ps1
Set-Location $PSScriptRoot
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$tessDir = "C:\Program Files\Tesseract-OCR"
if ((Test-Path "$tessDir\tesseract.exe") -and -not (Get-Command tesseract -ErrorAction SilentlyContinue)) { $env:PATH = "$tessDir;$env:PATH" }
& .\.venv\Scripts\Activate.ps1
python evaluate.py --extractor rules 2>&1 | Tee-Object -FilePath "after_log.txt"
Copy-Item results_rules.csv results_rules_after.csv -Force
Write-Host "`nDone: after_log.txt and results_rules_after.csv are in this folder."
