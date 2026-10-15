@echo off
rem Shared Python environment for both dashboards.
rem Stored outside OneDrive so the thousands of package files are not synced.
set "VENV=%LOCALAPPDATA%\ocr_portfolio_venv"
if exist "%VENV%\Scripts\python.exe" goto :eof
echo First run: setting up the Python environment (a few minutes)...
py -m venv "%VENV%" || goto :fail
"%VENV%\Scripts\python" -m pip install -q --upgrade pip
"%VENV%\Scripts\python" -m pip install -q pdfplumber pypdfium2 pillow numpy pytesseract requests streamlit plotly pandas winocr openpyxl || goto :fail
goto :eof
:fail
echo.
echo Setup failed. Please make sure Python is installed and the "py" command works.
pause
exit /b 1
