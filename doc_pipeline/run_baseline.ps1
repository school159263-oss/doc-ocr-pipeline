# One-shot baseline runner. Usage (PowerShell, inside doc_pipeline):
#   powershell -ExecutionPolicy Bypass -File .\run_baseline.ps1
# Every step keeps going even if one fails; everything is logged to baseline_log.txt.
# Nothing is sent anywhere except pip downloading packages. Rules are NOT modified.
$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
Start-Transcript -Path "baseline_log.txt" -Force | Out-Null

# If Tesseract is installed in the default folder but PATH is stale, add it for this session only.
$tessDir = "C:\Program Files\Tesseract-OCR"
if ((Test-Path "$tessDir\tesseract.exe") -and -not (Get-Command tesseract -ErrorAction SilentlyContinue)) {
    $env:PATH = "$tessDir;$env:PATH"
    Write-Host "(added $tessDir to PATH for this run)"
}

Write-Host "== [1] venv"
python --version 2>&1 | Out-Host
if (-not (Test-Path ".venv")) { python -m venv .venv 2>&1 | Out-Host }
& .\.venv\Scripts\Activate.ps1

Write-Host "== [2] install (paddle is skipped: no wheels for this Python; Tesseract is the OCR engine)"
python -m pip install --upgrade pip 2>&1 | Out-Host
pip install pdfplumber pypdfium2 pillow numpy opencv-python-headless reportlab pytesseract requests 2>&1 | Out-Host
pip list 2>&1 | Select-String -Pattern "paddle|pytesseract|pdfplumber|pypdfium2|opencv|reportlab" | Out-Host

Write-Host "== [3] OCR availability"
if (Get-Command tesseract -ErrorAction SilentlyContinue) {
    tesseract --version 2>&1 | Select-Object -First 1 | Out-Host
    tesseract --list-langs 2>&1 | Out-Host
} else { Write-Host "tesseract NOT found on PATH" }

Write-Host "== [4] generate test docs (Traditional Chinese, Microsoft JhengHei)"
python generate_docs.py 2>&1 | Out-Host

Write-Host "== [5] baseline: rules"
python evaluate.py --extractor rules 2>&1 | Out-Host

Write-Host "== [6] Ollama check (no download is attempted)"
if (Get-Command ollama -ErrorAction SilentlyContinue) { ollama list 2>&1 | Out-Host } else { Write-Host "ollama not installed - llm/routed skipped" }

Stop-Transcript | Out-Null
Write-Host "`nDone. Tell me it finished; I will read baseline_log.txt and results_rules.csv from this folder."
