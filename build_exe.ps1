# build_exe.ps1 — Build WinSnap as a standalone Windows .exe
# Prerequisites: pip install -r requirements.txt

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

function Invoke-Python {
    param([Parameter(Mandatory)][string[]]$Args)
    & python @Args
    if ($LASTEXITCODE -ne 0) {
        throw "python exited with code $LASTEXITCODE"
    }
}

# Step 1: Generate icon.ico (if missing)
if (-not (Test-Path -LiteralPath 'icon.ico')) {
    Write-Host 'Generating icon.ico ...'
    Invoke-Python -Args @('icon.py')
}

# Step 2: PyInstaller (via python -m, works when pyinstaller.exe is not on PATH)
Write-Host 'Building WinSnap.exe ...'
Invoke-Python -Args @(
    '-m', 'PyInstaller',
    '--onefile',
    '--windowed',
    '--icon=icon.ico',
    '--name=WinSnap',
    '--hidden-import=tkinter',
    '--add-data', 'icon.ico;.',
    'winsnap.py'
)

Write-Host ''
$exe = Join-Path $PSScriptRoot 'dist\WinSnap.exe'
if (Test-Path -LiteralPath $exe) {
    Write-Host "Build successful!  Executable: $exe"
    exit 0
}

Write-Host 'Build FAILED.  Check the output above for errors.'
exit 1
