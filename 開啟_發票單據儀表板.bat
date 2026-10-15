@echo off
call "%~dp0_setup_env.bat" || exit /b 1
cd /d "%~dp0doc_pipeline"
echo Opening dashboard at http://localhost:8601  (close this window to stop)
start "" cmd /c "timeout /t 5 >nul & start http://localhost:8601"
"%LOCALAPPDATA%\ocr_portfolio_venv\Scripts\python" -m streamlit run dashboard.py --server.port 8601 --server.headless true --browser.gatherUsageStats false
pause
