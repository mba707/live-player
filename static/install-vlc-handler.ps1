# Live Player VLC opener for Windows. Do not run as Administrator.
#   irm http://localhost:8112/static/install-vlc-handler.ps1 | iex
# Or:
#   powershell -ExecutionPolicy Bypass -Command "irm http://localhost:8112/static/install-vlc-handler.ps1 | iex"
$ErrorActionPreference = 'Stop'

function Find-VlcPath {
    $candidates = @(
        (Join-Path $env:ProgramFiles 'VideoLAN\VLC\vlc.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'VideoLAN\VLC\vlc.exe')
    )
    foreach ($path in $candidates) {
        if ($path -and (Test-Path -LiteralPath $path)) {
            return $path
        }
    }
    $fromPath = Get-Command vlc.exe -ErrorAction SilentlyContinue
    if ($fromPath) {
        return $fromPath.Source
    }
    return $null
}

$vlc = Find-VlcPath
if (-not $vlc) {
    Write-Error "VLC was not found. Install VLC first: https://www.videolan.org/vlc/"
}

$Dir = Join-Path $env:LOCALAPPDATA 'LivePlayer'
New-Item -ItemType Directory -Force -Path $Dir | Out-Null
$OpenerPs1 = Join-Path $Dir 'live-player-open.ps1'
$OpenerCmd = Join-Path $Dir 'live-player-open.cmd'

Write-Host "Installing Live Player VLC opener for Windows..."
Write-Host "VLC: $vlc"

@'
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Raw
)

function Get-StreamUrl([string]$RawUrl) {
    $url = $null
    if ($RawUrl -match '(?i)[?&]url=([^&]*)') {
        $url = [System.Uri]::UnescapeDataString($Matches[1])
    } else {
        $rest = $RawUrl -replace '(?i)^liveplayer:', ''
        $path = [System.Uri]::UnescapeDataString(($rest.TrimStart('/') -split '\?', 2)[0])
        if ($path.StartsWith('http:/') -and -not $path.StartsWith('http://')) {
            $url = 'http://' + $path.Substring(6)
        } else {
            $url = $path
        }
    }
    if (-not ($url.StartsWith('http://') -or $url.StartsWith('https://'))) {
        throw "live-player-open: refused '$RawUrl'"
    }
    return $url
}

function Find-VlcPath {
    $candidates = @(
        (Join-Path $env:ProgramFiles 'VideoLAN\VLC\vlc.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'VideoLAN\VLC\vlc.exe')
    )
    foreach ($path in $candidates) {
        if ($path -and (Test-Path -LiteralPath $path)) {
            return $path
        }
    }
    $fromPath = Get-Command vlc.exe -ErrorAction SilentlyContinue
    if ($fromPath) {
        return $fromPath.Source
    }
    throw 'live-player-open: VLC is not installed'
}

$streamUrl = Get-StreamUrl $Raw
$vlcPath = Find-VlcPath
Start-Process -FilePath $vlcPath -ArgumentList $streamUrl
'@ | Set-Content -LiteralPath $OpenerPs1 -Encoding UTF8

@"
@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0live-player-open.ps1" "%~1"
"@ | Set-Content -LiteralPath $OpenerCmd -Encoding ASCII

$protocolKey = 'HKCU:\Software\Classes\liveplayer'
New-Item -Path $protocolKey -Force | Out-Null
Set-ItemProperty -Path $protocolKey -Name '(Default)' -Value 'URL:Live Player Protocol'
Set-ItemProperty -Path $protocolKey -Name 'URL Protocol' -Value ''
New-Item -Path "$protocolKey\DefaultIcon" -Force | Out-Null
Set-ItemProperty -Path "$protocolKey\DefaultIcon" -Name '(Default)' -Value "`"$vlc`",0"
New-Item -Path "$protocolKey\shell\open\command" -Force | Out-Null
Set-ItemProperty -Path "$protocolKey\shell\open\command" -Name '(Default)' -Value "`"$OpenerCmd`" `"%1`""

Write-Host "Wrote $OpenerPs1"
Write-Host "Registered liveplayer: handler (HKCU)."
Write-Host ""
Write-Host "Done. Next steps:"
Write-Host "  1. Fully quit Chrome (use Exit / Quit, not just close the window)."
Write-Host "  2. Open Live Player again and click Play."
Write-Host "  3. If Chrome asks to open Live Player, click Open."
Write-Host "Handler: $OpenerCmd"
