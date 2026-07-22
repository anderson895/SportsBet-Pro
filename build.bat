@echo off
REM ============================================================
REM  SportsBet Pro — one-click PyInstaller build
REM  Output: dist\SportsBetPro\SportsBetPro.exe
REM ============================================================
cd /d "%~dp0"

echo.
echo [1/3] Installing PyInstaller (if needed)...
.\venv\Scripts\python.exe -m pip install --quiet pyinstaller

echo.
echo [2/3] Removing PyQt6 from the build venv (finplot pulls it in;
echo       PyInstaller refuses two Qt bindings)...
.\venv\Scripts\python.exe -m pip uninstall -y PyQt6 PyQt6-Qt6 PyQt6_sip 2>nul

echo.
echo [3/3] Building SportsBetPro.exe ...
.\venv\Scripts\python.exe -m PyInstaller --noconfirm SportsBetPro.spec

echo.
echo ============================================================
echo  Done. Run:  dist\SportsBetPro\SportsBetPro.exe
echo ============================================================
pause
