@echo off
title Stop KROVEX Discord Bot
echo Terminating running KROVEX Bot processes...
powershell -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*bot.main*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
echo All KROVEX bot processes stopped.
pause
