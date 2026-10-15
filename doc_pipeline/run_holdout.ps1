# Hold-out test: new random seed + layouts/labels/date styles the rules were never tuned on.
# Rules (extractors.py / validators.py) are NOT touched. The original docs/ and ground_truth.csv are NOT touched.
#   powershell -ExecutionPolicy Bypass -File .\run_holdout.ps1
Set-Location $PSScriptRoot
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$tessDir = "C:\Program Files\Tesseract-OCR"
if ((Test-Path "$tessDir\tesseract.exe") -and -not (Get-Command tesseract -ErrorAction SilentlyContinue)) { $env:PATH = "$tessDir;$env:PATH" }
& .\.venv\Scripts\Activate.ps1
$o1 = python generate_docs.py --holdout 2>&1
$o2 = python evaluate.py --extractor rules --docs docs_holdout --truth ground_truth_holdout.csv --out results_rules_holdout.csv 2>&1
$all = @($o1) + @($o2)
$all | Out-File -FilePath "holdout_log.txt" -Encoding utf8
$all | Out-Host
Write-Host "`nDone: holdout_log.txt and results_rules_holdout.csv are in this folder."
