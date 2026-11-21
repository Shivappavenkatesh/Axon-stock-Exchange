# Axon - Full AWS EC2 Mumbai Deployment From Windows Laptop
# Launches the EC2 VM, uploads the current repo over SSH, and bootstraps the app.

param(
    [string]$Region = "ap-south-1",
    [string]$InstanceName = "axon-mumbai-ec2",
    [string]$InstanceType = "t3.micro",
    [string]$KeyPairName = "axon-mumbai-key",
    [switch]$CreateKeyPairIfMissing,
    [string]$KeyOutputPath = ".\axon-mumbai-key.pem",
    [string]$VpcId = "",
    [string]$SubnetId = "",
    [string]$SecurityGroupName = "axon-mumbai-sg",
    [string]$AllowedSshCidr = "",
    [int]$RootVolumeGiB = 12,
    [switch]$OpenHttps,
    [switch]$UseArm,
    [string]$RemoteAppDir = "/opt/axon",
    [string]$RemoteUser = "ubuntu",
    [switch]$SkipLaunch,
    [string]$ExistingHost = "",
    [string]$ExistingKeyPath = "",
    [switch]$SkipBootstrap,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

function Write-Success { param($m) Write-Host $m -ForegroundColor Green }
function Write-Info    { param($m) Write-Host $m -ForegroundColor Yellow }
function Write-Err     { param($m) Write-Host $m -ForegroundColor Red }

function Assert-Command {
    param([string]$Name)

    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "$Name is required but not available on PATH."
    }
}

function New-StagingTree {
    param([string]$SourceRoot)

    $tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("axon-stage-" + [guid]::NewGuid().ToString("N"))
    $null = New-Item -ItemType Directory -Path $tempRoot

    $excludeDirs = @(".git", ".venv", "__pycache__", ".pytest_cache", "logs")
    $excludeFileNames = @("axon.db")
    $excludeExtensions = @(".pyc")

    Get-ChildItem -Path $SourceRoot -Force | Where-Object {
        $excludeDirs -notcontains $_.Name
    } | ForEach-Object {
        $destination = Join-Path $tempRoot $_.Name
        if ($_.PSIsContainer) {
            Copy-RepoItem -SourcePath $_.FullName -DestinationPath $destination -ExcludeDirs $excludeDirs -ExcludeFileNames $excludeFileNames -ExcludeExtensions $excludeExtensions
        } elseif (($excludeFileNames -notcontains $_.Name) -and ($excludeExtensions -notcontains $_.Extension)) {
            Copy-Item -Path $_.FullName -Destination $destination -Force
        }
    }

    return $tempRoot
}

function Copy-RepoItem {
    param(
        [string]$SourcePath,
        [string]$DestinationPath,
        [string[]]$ExcludeDirs,
        [string[]]$ExcludeFileNames,
        [string[]]$ExcludeExtensions
    )

    $item = Get-Item -LiteralPath $SourcePath
    if ($item.PSIsContainer) {
        if ($ExcludeDirs -contains $item.Name) {
            return
        }

        $null = New-Item -ItemType Directory -Path $DestinationPath -Force
        Get-ChildItem -LiteralPath $SourcePath -Force | ForEach-Object {
            Copy-RepoItem -SourcePath $_.FullName -DestinationPath (Join-Path $DestinationPath $_.Name) -ExcludeDirs $ExcludeDirs -ExcludeFileNames $ExcludeFileNames -ExcludeExtensions $ExcludeExtensions
        }
        return
    }

    if (($ExcludeFileNames -contains $item.Name) -or ($ExcludeExtensions -contains $item.Extension)) {
        return
    }

    Copy-Item -LiteralPath $SourcePath -Destination $DestinationPath -Force
}

function New-DeploymentArchive {
    param([string]$RepoRoot)

    $stagingRoot = New-StagingTree -SourceRoot $RepoRoot
    $archivePath = Join-Path ([System.IO.Path]::GetTempPath()) ("axon-package-" + [guid]::NewGuid().ToString("N") + ".zip")

    try {
        Compress-Archive -Path (Join-Path $stagingRoot "*") -DestinationPath $archivePath -CompressionLevel Optimal -Force
    } finally {
        Remove-Item -LiteralPath $stagingRoot -Recurse -Force -ErrorAction SilentlyContinue
    }

    return $archivePath
}

function Invoke-SshCommand {
    param(
        [string]$SshTarget,
        [string]$KeyPath,
        [string]$CommandText,
        [int]$TimeoutSec = 30
    )

    $sshArgs = @(
        "-i", $KeyPath,
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=$TimeoutSec",
        "${RemoteUser}@${SshTarget}",
        $CommandText
    )

    & ssh @sshArgs
    if ($LASTEXITCODE -ne 0) {
        throw "SSH command failed on $SshTarget"
    }
}

function Wait-ForSsh {
    param(
        [string]$SshTarget,
        [string]$KeyPath
    )

    for ($attempt = 1; $attempt -le 20; $attempt++) {
        try {
            Invoke-SshCommand -SshTarget $SshTarget -KeyPath $KeyPath -CommandText "echo ssh-ready" -TimeoutSec 10
            Write-Success "SSH is ready on $SshTarget"
            return
        } catch {
            Start-Sleep -Seconds 10
        }
    }

    throw "SSH did not become ready on $SshTarget in time."
}

function Copy-ArchiveToHost {
    param(
        [string]$SshTarget,
        [string]$KeyPath,
        [string]$ArchivePath
    )

    $scpArgs = @(
        "-i", $KeyPath,
        "-o", "StrictHostKeyChecking=accept-new",
        $ArchivePath,
        "${RemoteUser}@${SshTarget}:/tmp/axon-package.zip"
    )

    & scp @scpArgs
    if ($LASTEXITCODE -ne 0) {
        throw "SCP upload failed for $SshTarget"
    }
}

function Invoke-RemoteBootstrap {
    param(
        [string]$SshTarget,
        [string]$KeyPath,
        [switch]$EnableHttps
    )

    $enableNginx = if ($EnableHttps) { "1" } else { "1" }
    $remoteCommand = @"
sudo apt-get update && \
sudo apt-get install -y unzip && \
sudo mkdir -p $RemoteAppDir && \
sudo chown -R ${RemoteUser}:${RemoteUser} $RemoteAppDir && \
rm -rf $RemoteAppDir/* && \
unzip -oq /tmp/axon-package.zip -d $RemoteAppDir && \
cd $RemoteAppDir && \
sudo APP_USER=$RemoteUser ENABLE_WEB=1 ENABLE_NGINX=$enableNginx bash scripts/bootstrap-aws-free-tier.sh
"@

    Invoke-SshCommand -SshTarget $SshTarget -KeyPath $KeyPath -CommandText $remoteCommand -TimeoutSec 30
}

function Remove-RemoteArchive {
    param(
        [string]$SshTarget,
        [string]$KeyPath
    )

    try {
        Invoke-SshCommand -SshTarget $SshTarget -KeyPath $KeyPath -CommandText "rm -f /tmp/axon-package.zip" -TimeoutSec 10
    } catch {
    }
}

$repoRoot = Split-Path -Parent $PSCommandPath

Write-Success "==============================================="
Write-Success "Axon - Full Mumbai EC2 Deployment Wrapper"
Write-Success "==============================================="

Assert-Command -Name ssh
Assert-Command -Name scp

$hostName = $ExistingHost
$keyPath = $ExistingKeyPath
$launchResult = $null

if (-not $SkipLaunch) {
    Write-Info "Launching or locating the EC2 instance in Mumbai."
    $launchScript = Join-Path $repoRoot "deploy-aws-ec2-mumbai.ps1"
    $launchParams = @{
        Region = $Region
        InstanceName = $InstanceName
        InstanceType = $InstanceType
        KeyPairName = $KeyPairName
        KeyOutputPath = $KeyOutputPath
        SecurityGroupName = $SecurityGroupName
        RootVolumeGiB = $RootVolumeGiB
        OpenHttps = $OpenHttps
        UseArm = $UseArm
        PassThru = $true
    }

    if ($CreateKeyPairIfMissing) { $launchParams.CreateKeyPairIfMissing = $true }
    if ($VpcId) { $launchParams.VpcId = $VpcId }
    if ($SubnetId) { $launchParams.SubnetId = $SubnetId }
    if ($AllowedSshCidr) { $launchParams.AllowedSshCidr = $AllowedSshCidr }
    if ($DryRun) { $launchParams.DryRun = $true }

    $launchResult = & $launchScript @launchParams
    if ($LASTEXITCODE -ne 0) {
        throw "EC2 launch script failed. See the launch output above for the AWS error."
    }
    if ($DryRun) {
        Write-Info "Dry run completed. No VM launch or upload was performed."
        exit 0
    }

    $hostName = $launchResult.PublicIp
    $keyPath = $launchResult.KeyPath
}

if ([string]::IsNullOrWhiteSpace($hostName)) {
    throw "No target host available. Use the launcher flow or provide -ExistingHost."
}

if ([string]::IsNullOrWhiteSpace($keyPath)) {
    throw "No SSH key path available. Use the launcher flow or provide -ExistingKeyPath."
}

Wait-ForSsh -SshTarget $hostName -KeyPath $keyPath

if (-not $SkipBootstrap) {
    Write-Info "Packaging the current repo and uploading it to the EC2 instance."
    $archivePath = New-DeploymentArchive -RepoRoot $repoRoot
    try {
        Copy-ArchiveToHost -SshTarget $hostName -KeyPath $keyPath -ArchivePath $archivePath
        Write-Info "Running remote bootstrap and service setup."
        Invoke-RemoteBootstrap -SshTarget $hostName -KeyPath $keyPath -EnableHttps:$OpenHttps
        Remove-RemoteArchive -SshTarget $hostName -KeyPath $keyPath
    } finally {
        Remove-Item -LiteralPath $archivePath -Force -ErrorAction SilentlyContinue
    }
}

Write-Success ""
Write-Success "Mumbai deployment completed"
Write-Success "Host: $hostName"
Write-Success "SSH: ssh -i $keyPath $RemoteUser@$hostName"
Write-Success ""
Write-Info "Final required step: add your AWS credentials locally with 'aws configure' and add your Angel One plus web credentials on the VM in /etc/axon/axon.env."
Write-Info "After editing credentials on the VM, restart services: sudo systemctl restart axon-scheduler axon-web"