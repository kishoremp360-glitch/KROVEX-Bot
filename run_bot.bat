@echo off
title KROVEX Discord Bot
cd /d "F:\Death Bot"

:start
echo [%date% %time%] Starting KROVEX Discord Bot...
"C:\Users\kishore\AppData\Local\Python\pythoncore-3.14-64\python.exe" -m bot.main
echo [%date% %time%] Bot process terminated with exit code %ERRORLEVEL%.
echo Restarting in 5 seconds (Press Ctrl+C to terminate)...
timeout /t 5 /nobreak >nul
goto start
