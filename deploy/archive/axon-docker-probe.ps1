$log = "$env:TEMP\axon-docker-probe.log"
Remove-Item $log -ErrorAction SilentlyContinue

function Log { param($m) $ts = Get-Date -Format 'HH:mm:ss'; "$ts $m" | Tee-Object -FilePath $log -Append }

Log "Probing Docker daemon..."
$docker = Get-Command docker -ErrorAction SilentlyContinue
if (-not $docker) { Log "docker CLI not found"; exit 1 }

# Poll for daemon up to 90 seconds
$up = $false
for ($i = 1; $i -le 18; $i++) {
    $ctx = docker context use default 2>&1 | Out-String
    $ver = docker version --format '{{.Server.Version}}' 2>&1 | Out-String
    $ver = $ver.Trim()
    Log "attempt $i/18 - version: '$ver' context: '$($ctx.Trim())'"
    if ($ver -match '^\d+\.\d+') {
        $up = $true
        Log "DAEMON UP: $ver"
        break
    }
    Start-Sleep -Seconds 5
}

if (-not $up) {
    Log "DAEMON NOT UP after 90 seconds"
    # Check which Docker Desktop processes are running
    $procs = Get-Process | Where-Object Name -Match 'docker' | Select-Object Name,Id | Out-String
    Log "Docker processes: $procs"
    exit 1
}

Log "Docker daemon is running. Version: $ver"
