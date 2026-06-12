$ErrorActionPreference = "Stop"

$codexExe = Join-Path $env:LOCALAPPDATA "Programs\Codex-Fixed\Codex.exe"
if (-not (Test-Path -LiteralPath $codexExe)) {
    throw "Codex-Fixed was not found at $codexExe"
}

Start-Process -FilePath $codexExe
