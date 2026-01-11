param(
    [string]$PyInstaller = "pyinstaller"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path | Split-Path -Parent
$Spec = Join-Path $Root "packaging\dv_downloader.spec"

& $PyInstaller $Spec --noconfirm --clean
