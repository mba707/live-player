# Live Player VLC opener for Windows. Run in a normal (non-admin) PowerShell window:
#   irm http://<host>:8112/static/install-vlc-handler.ps1 | iex

$ErrorActionPreference = "Stop"

Write-Host "Installing Live Player VLC opener for Windows..."

$installDir = Join-Path $env:LOCALAPPDATA "LivePlayer"
New-Item -ItemType Directory -Path $installDir -Force | Out-Null
$openerPath = Join-Path $installDir "live-player-open.ps1"

$openerScript = @'
param([Parameter(Mandatory=$true)][string]$RawUrl)

function Get-StreamUrl([string]$raw) {
    if ($raw -notmatch "url=([^&]+)") {
        throw "live-player-open: could not find a url= parameter in '$raw'"
    }
    $decoded = [System.Uri]::UnescapeDataString($Matches[1])
    if (-not ($decoded.StartsWith("http://") -or $decoded.StartsWith("https://"))) {
        throw "live-player-open: refused '$raw'"
    }
    return $decoded
}

function Find-Vlc {
    $candidates = @(
        (Join-Path $env:ProgramFiles "VideoLAN\VLC\vlc.exe"),
        (Join-Path ${env:ProgramFiles(x86)} "VideoLAN\VLC\vlc.exe")
    )
    foreach ($path in $candidates) {
        if ($path -and (Test-Path $path)) { return $path }
    }
    $onPath = Get-Command vlc.exe -ErrorAction SilentlyContinue
    if ($onPath) { return $onPath.Source }
    throw "live-player-open: VLC is not installed. Get it from https://www.videolan.org/vlc/"
}

try {
    $streamUrl = Get-StreamUrl $RawUrl
    $vlc = Find-Vlc
    Start-Process -FilePath $vlc -ArgumentList $streamUrl
} catch {
    Add-Type -AssemblyName System.Windows.Forms
    [void][System.Windows.Forms.MessageBox]::Show($_.Exception.Message, "Live Player")
}
'@
Set-Content -Path $openerPath -Value $openerScript -Encoding UTF8
Write-Host "Wrote $openerPath"

$command = "powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$openerPath`" `"%1`""

New-Item -Path "HKCU:\Software\Classes\liveplayer" -Force | Out-Null
New-ItemProperty -Path "HKCU:\Software\Classes\liveplayer" -Name "(Default)" -Value "URL:Live Player Protocol" -PropertyType String -Force | Out-Null
New-ItemProperty -Path "HKCU:\Software\Classes\liveplayer" -Name "URL Protocol" -Value "" -PropertyType String -Force | Out-Null
New-Item -Path "HKCU:\Software\Classes\liveplayer\shell\open\command" -Force | Out-Null
New-ItemProperty -Path "HKCU:\Software\Classes\liveplayer\shell\open\command" -Name "(Default)" -Value $command -PropertyType String -Force | Out-Null

Write-Host ""
Write-Host "Done. Handler: $openerPath"
Write-Host "Next steps:"
Write-Host "  1. Fully quit Chrome (check the system tray and Task Manager for lingering chrome.exe)."
Write-Host "  2. Open Live Player again and click Play."
Write-Host "  3. If Chrome asks to open Live Player, click Open."
