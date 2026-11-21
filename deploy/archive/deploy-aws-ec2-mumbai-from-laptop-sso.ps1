# Axon - Full Mumbai Deployment via AWS SSO + SSM
# Launches a keyless EC2 instance, uploads the repo via temporary S3 object, and bootstraps through SSM.

param(
    [string]$Region = "ap-south-1",
    [string]$InstanceName = "axon-mumbai-ec2",
    [string]$InstanceType = "t3.micro",
    [string]$VpcId = "",
    [string]$SubnetId = "",
    [string]$SecurityGroupName = "axon-mumbai-sg",
    [int]$RootVolumeGiB = 12,
    [switch]$OpenHttps,
    [switch]$UseArm,
    [string]$RemoteAppDir = "/opt/axon",
    [switch]$SkipLaunch,
    [string]$ExistingInstanceId = "",
    [string]$BucketName = "",
    [switch]$KeepPackageInS3,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

function Write-Success { param($m) Write-Host $m -ForegroundColor Green }
function Write-Info    { param($m) Write-Host $m -ForegroundColor Yellow }
function Write-Err     { param($m) Write-Host $m -ForegroundColor Red }

function Resolve-AwsCliPath {
    $command = Get-Command aws -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    $fallback = "C:\Program Files\Amazon\AWSCLIV2\aws.exe"
    if (Test-Path $fallback) { return $fallback }
    throw "AWS CLI v2 is not installed."
}

function Invoke-AwsJson {
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
        throw "AWS CLI failed: $($output | Out-String)"
    }
    if (-not $output) { return $null }
    return ($output | Out-String) | ConvertFrom-Json
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
        throw "AWS CLI failed: $($output | Out-String)"
    }
    return ($output | Out-String).Trim()
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

function New-DeploymentBucket {
    param([string]$AccountId)

    if ([string]::IsNullOrWhiteSpace($BucketName)) {
        $script:BucketName = ("axon-deploy-{0}-{1}" -f $AccountId, $Region).ToLowerInvariant()
    }

    $exists = $true
    try {
        Invoke-AwsText @("s3api", "head-bucket", "--bucket", $BucketName) | Out-Null
    } catch {
        $exists = $false
    }

    if ($exists) {
        Write-Info "Reusing S3 deployment bucket: $BucketName"
        return
    }

    Write-Info "Creating temporary deployment bucket: $BucketName"
    Invoke-AwsText @(
        "s3api", "create-bucket",
        "--bucket", $BucketName,
        "--region", $Region,
        "--create-bucket-configuration", "LocationConstraint=$Region"
    ) | Out-Null
}

function Publish-PackageAndPresign {
    param([string]$ArchivePath)

    $objectKey = "packages/axon-{0}.zip" -f ([guid]::NewGuid().ToString("N"))
    Invoke-AwsText @("s3", "cp", $ArchivePath, "s3://$BucketName/$objectKey") | Out-Null
    $url = Invoke-AwsText @("s3", "presign", "s3://$BucketName/$objectKey", "--expires-in", "3600")
    return [pscustomobject]@{
        ObjectKey = $objectKey
        PresignedUrl = $url
    }
}

function Wait-ForCommand {
    param(
        [string]$CommandId,
        [string]$InstanceId
    )

    for ($attempt = 1; $attempt -le 60; $attempt++) {
        $invocation = Invoke-AwsJson @(
            "ssm", "get-command-invocation",
            "--region", $Region,
            "--command-id", $CommandId,
            "--instance-id", $InstanceId,
            "--output", "json"
        )

        if ($invocation.Status -in @("Success", "Failed", "Cancelled", "TimedOut", "Cancelling")) {
            return $invocation
        }

        Start-Sleep -Seconds 10
    }

    throw "SSM command $CommandId did not complete in time."
}

function Invoke-RemoteBootstrap {
    param(
        [string]$InstanceId,
        [string]$PackageUrl
    )

    $commands = @(
        "set -e",
        "sudo apt-get update",
        "sudo apt-get install -y curl unzip",
        "sudo mkdir -p $RemoteAppDir",
        "sudo chown -R ubuntu:ubuntu $RemoteAppDir",
        "curl -L '$PackageUrl' -o /tmp/axon-package.zip",
        "rm -rf $RemoteAppDir/*",
        "unzip -oq /tmp/axon-package.zip -d $RemoteAppDir",
        "cd $RemoteAppDir",
        "sudo APP_USER=ubuntu ENABLE_WEB=1 ENABLE_NGINX=1 bash scripts/bootstrap-aws-free-tier.sh"
    )

    $commandResult = Invoke-AwsJson @(
        "ssm", "send-command",
        "--region", $Region,
        "--instance-ids", $InstanceId,
        "--document-name", "AWS-RunShellScript",
        "--comment", "Axon deployment bootstrap",
        "--parameters", ("commands={0}" -f (($commands | ForEach-Object { '"' + $_ + '"' }) -join ',')),
        "--output", "json"
    )

    $commandId = $commandResult.Command.CommandId
    return Wait-ForCommand -CommandId $commandId -InstanceId $InstanceId
}

$repoRoot = Split-Path -Parent $PSCommandPath

Write-Success "===================================================="
Write-Success "Axon - Full Mumbai Deployment via SSO + SSM"
Write-Success "===================================================="

$identity = Invoke-AwsJson @("sts", "get-caller-identity", "--output", "json")

$instance = $null
if (-not $SkipLaunch) {
    $launchScript = Join-Path $repoRoot "deploy-aws-ec2-mumbai-sso.ps1"
    $launchParams = @{
        Region = $Region
        InstanceName = $InstanceName
        InstanceType = $InstanceType
        SecurityGroupName = $SecurityGroupName
        RootVolumeGiB = $RootVolumeGiB
        OpenHttps = $OpenHttps
        UseArm = $UseArm
        PassThru = $true
    }
    if ($VpcId) { $launchParams.VpcId = $VpcId }
    if ($SubnetId) { $launchParams.SubnetId = $SubnetId }
    if ($DryRun) { $launchParams.DryRun = $true }

    $instance = & $launchScript @launchParams
    if ($LASTEXITCODE -ne 0) {
        throw "SSO/SSM EC2 launch script failed."
    }
    if ($DryRun) {
        Write-Info "Dry run completed."
        exit 0
    }
    $ExistingInstanceId = $instance.InstanceId
} elseif ([string]::IsNullOrWhiteSpace($ExistingInstanceId)) {
    throw "Use -ExistingInstanceId when -SkipLaunch is set."
}

$archivePath = New-DeploymentArchive -RepoRoot $repoRoot
try {
    New-DeploymentBucket -AccountId $identity.Account
    $package = Publish-PackageAndPresign -ArchivePath $archivePath
    Write-Info "Running bootstrap through AWS Systems Manager."
    $invocation = Invoke-RemoteBootstrap -InstanceId $ExistingInstanceId -PackageUrl $package.PresignedUrl

    if ($invocation.Status -ne "Success") {
        throw "Bootstrap failed. Status: $($invocation.Status)`nSTDOUT:`n$($invocation.StandardOutputContent)`nSTDERR:`n$($invocation.StandardErrorContent)"
    }

    Write-Success ""
    Write-Success "Mumbai deployment completed via SSO + SSM"
    Write-Success "Instance ID: $ExistingInstanceId"
    Write-Success ""
    Write-Info "No .pem file was used or required."
    Write-Info "Next step: use Session Manager or SSM Run Command to edit /etc/axon/axon.env with your Angel One and web credentials, then restart services."
} finally {
    Remove-Item -LiteralPath $archivePath -Force -ErrorAction SilentlyContinue
    if ($package -and $package.ObjectKey -and -not $KeepPackageInS3) {
        try {
            Invoke-AwsText @("s3", "rm", "s3://$BucketName/$($package.ObjectKey)") | Out-Null
        } catch {
        }
    }
}