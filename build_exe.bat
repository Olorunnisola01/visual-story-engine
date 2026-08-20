@echo off
echo Building Visual Story Engine...
cd /d "%~dp0"

pyinstaller --noconfirm --onefile --windowed ^
  --add-binary "assets\ffmpeg.exe;assets" ^
  --add-binary "assets\ffprobe.exe;assets" ^
  --add-data "assets;assets" ^
  --name "Visual Story Engine" ^
  --icon NONE ^
  main.py

echo.
echo Build complete. EXE is in the dist\ folder.
pause
