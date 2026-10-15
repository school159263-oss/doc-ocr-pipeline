# Vendor master-data fuzzy matching, run on BOTH batches. Rules (extractors.py) are NOT touched.
# Similarity threshold is fixed at 0.85 (validators.SIM_THRESHOLD); 0.80 / 0.90 are reported as sensitivity only.
#   powershell -ExecutionPolicy Bypass -File .\run_vendor.ps1
Set-Location $PSScriptRoot
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$tessDir = "C:\Program Files\Tesseract-OCR"
if ((Test-Path "$tessDir\tesseract.exe") -and -not (Get-Command tesseract -ErrorAction SilentlyContinue)) { $env:PATH = "$tessDir;$env:PATH" }
& .\.venv\Scripts\Activate.ps1
$o0 = python make_vendor_master.py 2>&1
$o1 = python evaluate.py --extractor rules --docs docs --truth ground_truth.csv --out results_rules_vendor.csv 2>&1
$o2 = python evaluate.py --extractor rules --docs docs_holdout --truth ground_truth_holdout.csv --out results_rules_holdout_vendor.csv 2>&1
$all = @("## master") + @($o0) + @("", "## original 20 docs") + @($o1) + @("", "## holdout 20 docs") + @($o2)
$all | Out-File -FilePath "vendor_log.txt" -Encoding utf8
$all | Out-Host
Write-Host "`nDone: vendor_log.txt, results_rules_vendor.csv, results_rules_holdout_vendor.csv are in this folder."
