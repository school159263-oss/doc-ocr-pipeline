@echo off
call "%~dp0_setup_env.bat" || exit /b 1
cd /d "%~dp0order_ocr"
echo Opening dashboard at http://localhost:8602  (close this window to stop)
start "" cmd /c "timeout /t 5 >nul & start http://localhost:8602"
"%LOCALAPPDATA%\ocr_portfolio_venv\Scripts\python" -m streamlit run dashboard.py --server.port 8602 --server.headless true --browser.gatherUsageStats false
pause
