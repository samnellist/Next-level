# Clip HQ installer for Windows. Run it by double-clicking "Install Clip HQ.bat".
# Safe to run again: it skips anything already done.
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # makes downloads much faster
Set-Location -LiteralPath $PSScriptRoot
$Root = $PSScriptRoot
New-Item -ItemType Directory -Force -Path (Join-Path $Root "data"), (Join-Path $Root "bin") | Out-Null

function Step($n, $msg) { Write-Host ""; Write-Host "[$n/6] $msg" -ForegroundColor Cyan }
function Ok($msg)   { Write-Host "      OK  $msg" -ForegroundColor Green }
function Info($msg) { Write-Host "      $msg" }
function Fail($msg) { Write-Host ""; Write-Host "PROBLEM: $msg" -ForegroundColor Red; Write-Host "Take a photo of this window and see 'Fixing problems' in README.md."; exit 1 }

Write-Host "=============================================" -ForegroundColor Magenta
Write-Host "   Installing Clip HQ (free, runs locally)" -ForegroundColor Magenta
Write-Host "=============================================" -ForegroundColor Magenta

# ---------------------------------------------------------------- 1. processor
Step 1 "Checking your processor"
$cpuInfo = Get-CimInstance Win32_Processor | Select-Object -First 1
$cpu = $cpuInfo.Name.Trim()
# Win32_Processor.Architecture: 9 = x64, 12 = ARM64
$isArm = ($cpuInfo.Architecture -eq 12) -or ($cpu -match "Snapdragon|Qualcomm|ARM") -or ($env:PROCESSOR_ARCHITECTURE -eq "ARM64")
$ramGB = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB)
$cores = (Get-CimInstance Win32_ComputerSystem).NumberOfLogicalProcessors
Info "Processor: $cpu"
Info "Memory: $ramGB GB    Threads: $cores"
if ($isArm) {
    Ok "ARM / Snapdragon laptop."
    Info "-> FFmpeg: native ARM64 build (fast video work)."
    Info "-> Python: the standard x64 version. The speech engine (faster-whisper) has no ARM build yet,"
    Info "   so Windows runs it with its built-in x64 emulation. It works, just a little slower."
    $ffArch = "winarm64"
} else {
    Ok "Intel / AMD (x64) laptop: using x64 versions of everything."
    $ffArch = "win64"
}
"cpu=$cpu`narm=$isArm`nram=$ramGB`nthreads=$cores" | Out-File -Encoding utf8 (Join-Path $Root "data\system.txt") -ErrorAction SilentlyContinue

# ---------------------------------------------------------------- 2. python
Step 2 "Python 3.12 (x64)"
$py = $null
$candidates = @("$env:LOCALAPPDATA\Programs\Python\Python312\python.exe", "$env:ProgramFiles\Python312\python.exe")
foreach ($c in $candidates) { if (Test-Path $c) { $py = $c; break } }
if (-not $py) {
    try {
        $p = & py -3.12-64 -c "import sys,platform; print(sys.executable if platform.machine()=='AMD64' else '')" 2>$null
        if ($LASTEXITCODE -eq 0 -and $p) { $py = $p.Trim() }
    } catch {}
}
if (-not $py) {
    Info "Downloading Python 3.12 (about 25 MB)..."
    $pyExe = Join-Path $env:TEMP "python-3.12.10-amd64.exe"
    try { Invoke-WebRequest "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe" -OutFile $pyExe }
    catch { Fail "Couldn't download Python. Check your internet connection and run the installer again." }
    Info "Installing Python just for your user (no admin needed)..."
    Start-Process -FilePath $pyExe -ArgumentList "/quiet InstallAllUsers=0 PrependPath=0 Include_launcher=0 Include_test=0 Include_doc=0 Shortcuts=0" -Wait
    $py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
    if (-not (Test-Path $py)) { Fail "Python didn't install. Try running 'Install Clip HQ.bat' again." }
}
Ok "Python: $py"

# ---------------------------------------------------------------- 3. ffmpeg
Step 3 "FFmpeg (video engine)"
$ffmpeg = Join-Path $Root "bin\ffmpeg.exe"
if (-not (Test-Path $ffmpeg)) {
    $zip = Join-Path $env:TEMP "cliphq-ffmpeg.zip"
    $url = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-$ffArch-gpl.zip"
    Info "Downloading FFmpeg for $ffArch (about 150 MB)..."
    try { Invoke-WebRequest $url -OutFile $zip }
    catch {
        if ($ffArch -eq "winarm64") {
            Info "ARM build not available right now, using the x64 build instead."
            Invoke-WebRequest "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip" -OutFile $zip
        } else { Fail "Couldn't download FFmpeg. Check your internet and try again." }
    }
    $tmp = Join-Path $env:TEMP "cliphq-ffmpeg"
    if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
    Expand-Archive -LiteralPath $zip -DestinationPath $tmp -Force
    $binDir = Get-ChildItem -Path $tmp -Recurse -Directory -Filter bin | Select-Object -First 1
    Copy-Item (Join-Path $binDir.FullName "ffmpeg.exe") (Join-Path $Root "bin") -Force
    Copy-Item (Join-Path $binDir.FullName "ffprobe.exe") (Join-Path $Root "bin") -Force
    Remove-Item -Recurse -Force $tmp; Remove-Item -Force $zip
}
& $ffmpeg -hide_banner -version | Select-Object -First 1 | ForEach-Object { Ok $_ }

# ---------------------------------------------------------------- 4. packages
Step 4 "Python packages (a few minutes the first time)"
$venvPy = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    & $py -m venv (Join-Path $Root ".venv")
    if ($LASTEXITCODE -ne 0) { Fail "Couldn't create the Python environment." }
}
& $venvPy -m pip install --upgrade pip --quiet --disable-pip-version-check
& $venvPy -m pip install -r (Join-Path $Root "requirements.txt") --disable-pip-version-check
if ($LASTEXITCODE -ne 0) { Fail "Package install failed (see the red text above)." }
& $venvPy -m pip install --no-deps rapidocr-onnxruntime --disable-pip-version-check --quiet
Ok "Packages installed"

# ---------------------------------------------------------------- 5. models
Step 5 "Downloading free AI models and caption fonts"
& $venvPy (Join-Path $Root "setup_models.py")
if ($LASTEXITCODE -ne 0) { Info "Some downloads had problems. Clip HQ will retry the speech model the first time you process a video." }

# ---------------------------------------------------------------- 6. shortcut
Step 6 "Desktop shortcut"
$desktop = [Environment]::GetFolderPath("Desktop")
$ws = New-Object -ComObject WScript.Shell
$lnk = $ws.CreateShortcut((Join-Path $desktop "Clip HQ.lnk"))
$lnk.TargetPath = Join-Path $Root "Start Clip HQ.bat"
$lnk.WorkingDirectory = $Root
$lnk.IconLocation = (Join-Path $Root "static\cliphq.ico")
$lnk.Description = "Start Clip HQ"
$lnk.Save()
Ok "'Clip HQ' shortcut added to your desktop"

Write-Host ""
Write-Host "=============================================" -ForegroundColor Green
Write-Host "  All done!  Double-click 'Clip HQ' on your desktop." -ForegroundColor Green
Write-Host "  The first time, Windows may ask about network access:" -ForegroundColor Green
Write-Host "  tick 'Private networks' and click Allow (needed for your phone)." -ForegroundColor Green
Write-Host "=============================================" -ForegroundColor Green
