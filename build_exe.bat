@echo off
pushd "%~dp0"
:: ============================================================
:: build_exe.bat — Build WinSnap v2 as a standalone Windows .exe
:: ============================================================
:: Prerequisites:
::   pip install -r requirements.txt
::   (uses: python -m PyInstaller)
:: ============================================================

:: Step 1: Generate icon.ico (if not already present)
if not exist icon.ico (
    echo Generating icon.ico ...
    python icon.py
)

:: Step 2: Run PyInstaller
echo Building WinSnap.exe ...
python -m PyInstaller ^
    --onefile ^
    --windowed ^
    --icon=icon.ico ^
    --name=WinSnap ^
    --hidden-import=tkinter ^
    --add-data "icon.ico;." ^
    winsnap.py

echo.
if exist dist\WinSnap.exe (
    echo Build successful!  Executable: dist\WinSnap.exe
) else (
    echo Build FAILED.  Check the output above for errors.
    exit /b 1
)
