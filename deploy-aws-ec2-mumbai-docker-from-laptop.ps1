# Axon - AWS EC2 Mumbai Docker Deployment From Windows Laptop
# Launches EC2, uploads the repo, builds Docker image on VM, and runs a single app container.

param(
    [string]$Region = "ap-south-1",
    [string]$InstanceName = "axon-mumbai-ec2",
    [string]$InstanceType = "t3.micro",
    [string]$KeyPairName = "axon-mumbai-key",
    [switch]$CreateKeyPairIfMissing,
    [string]$KeyOutputPath = ".\\axon-mumbai-key.pem",
    [string]$VpcId = "",
    [string]$SubnetId = "",
    [string]$SecurityGroupName = "axon-mumbai-sg",
    [string]$AllowedSshCidr = "",
    [int]$RootVolumeGiB = 12,
    [switch]$UseArm,
    [string]$RemoteAppDir = "/opt/axon",
    [string]$RemoteUser = "ubuntu",
    [string]$ContainerName = "axon-app",
    [string]$ImageName = "axon-app:latest",
    [string]$DataVolumeName = "axon-data",
    [string]$TradeMode = "PAPER",
    [string]$ApiKey = $env:ANGEL_ONE_API_KEY,
    [string]$ClientId = $env:ANGEL_ONE_CLIENT_ID,
    [string]$Pin = $env:ANGEL_ONE_PIN,
    [string]$TotpSecret = $env:ANGEL_ONE_TOTP_SECRET,
    [string]$WebUsername = $(if ($env:WEB_USERNAME) { $env:WEB_USERNAME } else { "admin" }),
    [string]$WebUiAuthSecret = $(if ($env:WEB_PASSWORD) { $env:WEB_PASSWORD } else { "change-this-before-public-access" }),
    [int]$MarketScanBatchSize = $(if ($env:AXON_MARKET_SCAN_BATCH_SIZE) { [int]$env:AXON_MARKET_SCAN_BATCH_SIZE } else { 10 }),
    [switch]$DisablePublicDashboard,
    [string]$DashboardCidr = "",
    [switch]$SkipLaunch,
    [string]$ExistingHost = "",
    [string]$ExistingKeyPath = "",
    [string]$ExistingSecurityGroupId = "",
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

function Resolve-AwsCliPath {
    $command = Get-Command aws -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    $fallback = "C:\\Program Files\\Amazon\\AWSCLIV2\\aws.exe"
    if (Test-Path $fallback) {
        return $fallback
    }

    throw "AWS CLI v2 is required for EC2 launch and security group updates."
}

function Format-AwsOutput {
    param($Output)
    ($Output | ForEach-Object {
        if ($_ -is [System.Management.Automation.ErrorRecord]) { $_.Exception.Message }
        else { $_ }
    }) -join "`n"
}

function Invoke-AwsText {
    param([string[]]$Arguments)

    $awsCli = Resolve-AwsCliPath
    $nativePrefVar = Get-Variable -Name PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue
    $previousNativePref = $null
    if ($nativePrefVar) {
        $previousNativePref = $nativePrefVar.Value
        $script:PSNativeCommandUseErrorActionPreference = $false
    }

    try {
        $output = & $awsCli @Arguments 2>&1
        $exitCode = $LASTEXITCODE
    } finally {
        if ($nativePrefVar) {
            $script:PSNativeCommandUseErrorActionPreference = $previousNativePref
        }
    }

    if ($exitCode -ne 0) {
        throw "AWS CLI failed: $(Format-AwsOutput $output)"
    }

    return (($output | Where-Object { $_ -isnot [System.Management.Automation.ErrorRecord] }) -join "`n").Trim()
}

function Get-PublicIpCidr {
    $ip = (Invoke-RestMethod -Uri "https://checkip.amazonaws.com/").Trim()
    return "$ip/32"
}

function Add-DashboardIngressRule {
    param(
        [string]$SecurityGroupId,
        [string]$IngressCidr
    )

    if ([string]::IsNullOrWhiteSpace($SecurityGroupId)) {
        Write-Info "Security group ID not available. Skipping automatic dashboard rule setup."
        return
    }

    if ([string]::IsNullOrWhiteSpace($IngressCidr)) {
        throw "Dashboard CIDR cannot be empty when opening dashboard ingress."
    }

    $ruleObj = @(
        @{
            IpProtocol = "tcp"
            FromPort = 8501
            ToPort = 8501
            IpRanges = @(
                @{
                    CidrIp = $IngressCidr
                    Description = "Axon Dashboard"
                }
            )
        }
    )
    $ruleJson = ConvertTo-Json -InputObject $ruleObj -Compress -Depth 6

    try {
        Invoke-AwsText @(
            "ec2", "authorize-security-group-ingress",
            "--region", $Region,
            "--group-id", $SecurityGroupId,
            "--ip-permissions", $ruleJson,
            "--output", "text"
        ) | Out-Null
        Write-Success "Opened dashboard ingress on 8501/tcp for $IngressCidr"
    } catch {
        if ($_.Exception.Message -match "InvalidPermission.Duplicate") {
            Write-Info "Dashboard ingress already present for 8501/tcp"
        } else {
            throw
        }
    }
}

function New-StagingTree {
    param([string]$SourceRoot)

    $tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("axon-stage-" + [guid]::NewGuid().ToString("N"))
    $null = New-Item -ItemType Directory -Path $tempRoot

    $excludeDirs = @(".git", ".venv", "__pycache__", ".pytest_cache", "logs")
    $excludeFileNames = @("axon.db")
    $excludeExtensions = @(".pyc")

    function Copy-RepoItem {
        param(
            [string]$SourcePath,
            [string]$DestinationPath
        )

        $item = Get-Item -LiteralPath $SourcePath
        if ($item.PSIsContainer) {
            if ($excludeDirs -contains $item.Name) { return }
            $null = New-Item -ItemType Directory -Path $DestinationPath -Force
            Get-ChildItem -LiteralPath $SourcePath -Force | ForEach-Object {
                Copy-RepoItem -SourcePath $_.FullName -DestinationPath (Join-Path $DestinationPath $_.Name)
            }
            return
        }

        if (($excludeFileNames -contains $item.Name) -or ($excludeExtensions -contains $item.Extension)) { return }
        Copy-Item -LiteralPath $SourcePath -Destination $DestinationPath -Force
    }

    Get-ChildItem -Path $SourceRoot -Force | Where-Object { $excludeDirs -notcontains $_.Name } | ForEach-Object {
        Copy-RepoItem -SourcePath $_.FullName -DestinationPath (Join-Path $tempRoot $_.Name)
    }

    return $tempRoot
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

function New-EnvFile {
    $tempEnv = Join-Path ([System.IO.Path]::GetTempPath()) ("axon-docker-env-" + [guid]::NewGuid().ToString("N") + ".env")

    $lines = @(
        "AXON_DATABASE_URL=sqlite:////app/data/axon.db",
        "AXON_TRADE_MODE=$TradeMode",
        "AXON_MARKET_SCAN_BATCH_SIZE=$MarketScanBatchSize",
        "WEB_USERNAME=$WebUsername",
        "WEB_PASSWORD=$WebUiAuthSecret"
    )

    if (-not [string]::IsNullOrWhiteSpace($ApiKey)) {
        $lines += "ANGEL_ONE_API_KEY=$ApiKey"
    }
    if (-not [string]::IsNullOrWhiteSpace($ClientId)) {
        $lines += "ANGEL_ONE_CLIENT_ID=$ClientId"
    }
    if (-not [string]::IsNullOrWhiteSpace($Pin)) {
        $lines += "ANGEL_ONE_PIN=$Pin"
    }
    if (-not [string]::IsNullOrWhiteSpace($TotpSecret)) {
        $lines += "ANGEL_ONE_TOTP_SECRET=$TotpSecret"
    }

    Set-Content -Path $tempEnv -Value ($lines -join "`n") -NoNewline
    return $tempEnv
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

function Copy-FileToHost {
    param(
        [string]$SshTarget,
        [string]$KeyPath,
        [string]$SourcePath,
        [string]$DestinationPath
    )

    $scpArgs = @(
        "-i", $KeyPath,
        "-o", "StrictHostKeyChecking=accept-new",
        $SourcePath,
        "${RemoteUser}@${SshTarget}:$DestinationPath"
    )

    & scp @scpArgs
    if ($LASTEXITCODE -ne 0) {
        throw "SCP upload failed for $SshTarget"
    }
}

function Invoke-RemoteDockerDeploy {
    param(
        [string]$SshTarget,
        [string]$KeyPath,
        [switch]$PublishDashboardPort
    )

    $dashboardPortMapping = if ($PublishDashboardPort) { "-p 8501:8501" } else { "" }

    $remoteCommand = @"
set -e
sudo apt-get update
sudo apt-get install -y unzip docker.io
sudo systemctl enable docker
sudo systemctl start docker
sudo mkdir -p $RemoteAppDir
sudo chown -R ${RemoteUser}:${RemoteUser} $RemoteAppDir
rm -rf $RemoteAppDir/*
unzip -oq /tmp/axon-package.zip -d $RemoteAppDir
mv /tmp/axon-docker.env $RemoteAppDir/.env.docker
cd $RemoteAppDir
sudo docker build -t $ImageName .
sudo docker volume create $DataVolumeName >/dev/null
sudo docker rm -f $ContainerName >/dev/null 2>&1 || true
sudo docker run -d \
  --name $ContainerName \
  --restart unless-stopped \
  --env-file $RemoteAppDir/.env.docker \
    -v $($DataVolumeName):/app/data \
  -p 80:5000 \
  $dashboardPortMapping \
  $ImageName \
  bash scripts/container/start-services.sh
sudo docker ps --filter name=$ContainerName
"@

    Invoke-SshCommand -SshTarget $SshTarget -KeyPath $KeyPath -CommandText $remoteCommand -TimeoutSec 45
}

function Remove-RemoteFiles {
    param(
        [string]$SshTarget,
        [string]$KeyPath
    )

    try {
        Invoke-SshCommand -SshTarget $SshTarget -KeyPath $KeyPath -CommandText "rm -f /tmp/axon-package.zip /tmp/axon-docker.env" -TimeoutSec 10
    } catch {
    }
}

$repoRoot = Split-Path -Parent $PSCommandPath

Write-Success "==========================================================="
Write-Success "Axon - AWS Mumbai Docker Deployment (Laptop -> EC2)"
Write-Success "==========================================================="

Assert-Command -Name ssh
Assert-Command -Name scp
Resolve-AwsCliPath | Out-Null

$hostName = $ExistingHost
$keyPath = $ExistingKeyPath
$securityGroupId = $ExistingSecurityGroupId
$launchResult = $null
$publishDashboard = -not $DisablePublicDashboard

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
        throw "EC2 launch script failed. See launch output above for AWS error details."
    }

    if ($DryRun) {
        Write-Info "Dry run completed. No VM launch or Docker deploy was performed."
        exit 0
    }

    $hostName = $launchResult.PublicIp
    $keyPath = $launchResult.KeyPath
    $securityGroupId = $launchResult.SecurityGroupId
}

if ([string]::IsNullOrWhiteSpace($hostName)) {
    throw "No target host available. Use launch flow or provide -ExistingHost."
}

if ([string]::IsNullOrWhiteSpace($keyPath)) {
    throw "No SSH key path available. Use launch flow or provide -ExistingKeyPath."
}

if ($publishDashboard) {
    if ([string]::IsNullOrWhiteSpace($DashboardCidr)) {
        if (-not [string]::IsNullOrWhiteSpace($AllowedSshCidr)) {
            $DashboardCidr = $AllowedSshCidr
        } else {
            $DashboardCidr = Get-PublicIpCidr
        }
    }
    Add-DashboardIngressRule -SecurityGroupId $securityGroupId -IngressCidr $DashboardCidr
}

Wait-ForSsh -SshTarget $hostName -KeyPath $keyPath

if (-not $SkipBootstrap) {
    Write-Info "Packaging the current repo and uploading it to the EC2 instance."
    $archivePath = New-DeploymentArchive -RepoRoot $repoRoot
    $envFile = New-EnvFile

    try {
        Copy-FileToHost -SshTarget $hostName -KeyPath $keyPath -SourcePath $archivePath -DestinationPath "/tmp/axon-package.zip"
        Copy-FileToHost -SshTarget $hostName -KeyPath $keyPath -SourcePath $envFile -DestinationPath "/tmp/axon-docker.env"
        Write-Info "Building image on VM and starting single-container runtime (scheduler + web + dashboard)."
        Invoke-RemoteDockerDeploy -SshTarget $hostName -KeyPath $keyPath -PublishDashboardPort:$publishDashboard
        Remove-RemoteFiles -SshTarget $hostName -KeyPath $keyPath
    } finally {
        Remove-Item -LiteralPath $archivePath -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $envFile -Force -ErrorAction SilentlyContinue
    }
}

Write-Success ""
Write-Success "Mumbai Docker deployment completed"
Write-Success "Host: $hostName"
Write-Success "SSH: ssh -i $keyPath $RemoteUser@$hostName"
Write-Success "Web UI: http://$hostName"
if ($publishDashboard) {
    Write-Success "Dashboard: http://$hostName:8501"
} else {
    Write-Info "Dashboard is running in the container but port 8501 is not publicly exposed."
    Write-Info "Use SSH tunnel if needed: ssh -i $keyPath -L 8501:localhost:8501 $RemoteUser@$hostName"
}
Write-Success ""
Write-Info "Container checks on VM:"
Write-Host "  sudo docker ps"
Write-Host "  sudo docker logs -f $ContainerName"
Write-Host "  sudo docker exec -it $ContainerName ls -lah /app/data"
