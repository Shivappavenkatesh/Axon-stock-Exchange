# Axon - AWS EC2 Deployment Script for Mumbai Region
# Launches the cheapest low-friction Ubuntu VM for this repo in ap-south-1.

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
    [string]$RepoUrl = "",
    [string]$RepoBranch = "main",
    [switch]$OpenHttps,
    [switch]$UseArm,
    [switch]$DryRun,
    [switch]$PassThru
)

$ErrorActionPreference = "Stop"
$script:AwsCliPath = $null

function Write-Success { param($m) Write-Host $m -ForegroundColor Green }
function Write-Info    { param($m) Write-Host $m -ForegroundColor Yellow }
function Write-Err     { param($m) Write-Host $m -ForegroundColor Red }

function Resolve-AwsCliPath {
    if ($script:AwsCliPath) {
        return $script:AwsCliPath
    }

    $command = Get-Command aws -ErrorAction SilentlyContinue
    if ($command) {
        $script:AwsCliPath = $command.Source
        return $script:AwsCliPath
    }

    $fallback = "C:\Program Files\Amazon\AWSCLIV2\aws.exe"
    if (Test-Path $fallback) {
        $script:AwsCliPath = $fallback
        return $script:AwsCliPath
    }

    throw "AWS CLI is not installed or not on PATH. Install AWS CLI v2 and run 'aws configure' first."
}

function Format-AwsOutput {
    param($Output)
    ($Output | ForEach-Object {
        if ($_ -is [System.Management.Automation.ErrorRecord]) { $_.Exception.Message }
        else { $_ }
    }) -join "`n"
}

function Invoke-AwsJson {
    param([string[]]$Arguments)

    $awsCli = Resolve-AwsCliPath
    $ErrorActionPreference = 'Continue'
    $PSNativeCommandUseErrorActionPreference = $false

    $output = & $awsCli @Arguments 2>&1
    $exitCode = $LASTEXITCODE

    if ($exitCode -ne 0) {
        throw "AWS CLI failed: $(Format-AwsOutput $output)"
    }

    if (-not $output) {
        return $null
    }

    return (($output | Where-Object { $_ -isnot [System.Management.Automation.ErrorRecord] }) -join "`n") | ConvertFrom-Json
}

function Invoke-AwsText {
    param([string[]]$Arguments)

    $awsCli = Resolve-AwsCliPath
    $ErrorActionPreference = 'Continue'
    $PSNativeCommandUseErrorActionPreference = $false

    $output = & $awsCli @Arguments 2>&1
    $exitCode = $LASTEXITCODE

    if ($exitCode -ne 0) {
        throw "AWS CLI failed: $(Format-AwsOutput $output)"
    }

    return (($output | Where-Object { $_ -isnot [System.Management.Automation.ErrorRecord] }) -join "`n").Trim()
}

function Get-PublicIpCidr {
    $ip = (Invoke-RestMethod -Uri "https://checkip.amazonaws.com/").Trim()
    return "$ip/32"
}

function Ensure-KeyPair {
    $existing = Invoke-AwsJson @(
        "ec2", "describe-key-pairs",
        "--region", $Region,
        "--filters", "Name=key-name,Values=$KeyPairName",
        "--output", "json"
    )

    if ($existing.KeyPairs -and $existing.KeyPairs.Count -gt 0) {
        $script:LocalKeyPath = if (Test-Path $KeyOutputPath) { $KeyOutputPath } else { "<path-to-your-existing-pem-file>" }
        Write-Info "Reusing key pair: $KeyPairName"
        return
    }

    if (-not $CreateKeyPairIfMissing) {
        throw "Key pair '$KeyPairName' does not exist in $Region. Re-run with -CreateKeyPairIfMissing or create it manually."
    }

    if (Test-Path $KeyOutputPath) {
        throw "Key output path already exists: $KeyOutputPath"
    }

    Write-Info "Creating key pair: $KeyPairName"
    $created = Invoke-AwsJson @(
        "ec2", "create-key-pair",
        "--region", $Region,
        "--key-name", $KeyPairName,
        "--key-type", "rsa",
        "--output", "json"
    )

    Set-Content -Path $KeyOutputPath -Value $created.KeyMaterial -NoNewline

    # Lock down permissions so OpenSSH accepts the key.
    # Windows OpenSSH requires FullControl for the owner of an identity file
    # (Read-only causes type -1 / silent load failure in ssh.exe).
    icacls $KeyOutputPath /inheritance:r /grant:r "$([System.Security.Principal.WindowsIdentity]::GetCurrent().Name):F" | Out-Null

    $script:LocalKeyPath = $KeyOutputPath
    Write-Success "Saved private key to $KeyOutputPath (permissions locked to current user)"
}

function Resolve-VpcAndSubnet {
    if (-not $VpcId) {
        $defaultVpc = Invoke-AwsJson @(
            "ec2", "describe-vpcs",
            "--region", $Region,
            "--filters", "Name=isDefault,Values=true",
            "--output", "json"
        )

        if (-not $defaultVpc.Vpcs -or $defaultVpc.Vpcs.Count -eq 0) {
            throw "No default VPC found in $Region. Supply -VpcId and -SubnetId explicitly."
        }

        $script:VpcId = $defaultVpc.Vpcs[0].VpcId
    }

    if (-not $SubnetId) {
        $subnets = Invoke-AwsJson @(
            "ec2", "describe-subnets",
            "--region", $Region,
            "--filters", "Name=vpc-id,Values=$VpcId", "Name=default-for-az,Values=true",
            "--output", "json"
        )

        if (-not $subnets.Subnets -or $subnets.Subnets.Count -eq 0) {
            throw "No default subnet found in VPC $VpcId. Supply -SubnetId explicitly."
        }

        $preferredSubnet = $subnets.Subnets | Sort-Object AvailabilityZone | Select-Object -First 1
        $script:SubnetId = $preferredSubnet.SubnetId
        $script:AvailabilityZone = $preferredSubnet.AvailabilityZone
    } else {
        $subnet = Invoke-AwsJson @(
            "ec2", "describe-subnets",
            "--region", $Region,
            "--subnet-ids", $SubnetId,
            "--output", "json"
        )
        $script:AvailabilityZone = $subnet.Subnets[0].AvailabilityZone
    }
}

function Ensure-SecurityGroup {
    $groups = Invoke-AwsJson @(
        "ec2", "describe-security-groups",
        "--region", $Region,
        "--filters", "Name=group-name,Values=$SecurityGroupName", "Name=vpc-id,Values=$VpcId",
        "--output", "json"
    )

    if ($groups.SecurityGroups.Count -gt 0) {
        $securityGroup = $groups.SecurityGroups[0]
        $script:SecurityGroupId = $securityGroup.GroupId
        Write-Info "Reusing security group: $SecurityGroupName ($SecurityGroupId)"
    } else {
        $created = Invoke-AwsJson @(
            "ec2", "create-security-group",
            "--region", $Region,
            "--group-name", $SecurityGroupName,
            "--description", "Axon EC2 access for web and SSH",
            "--vpc-id", $VpcId,
            "--output", "json"
        )
        $script:SecurityGroupId = $created.GroupId
        $securityGroup = Invoke-AwsJson @(
            "ec2", "describe-security-groups",
            "--region", $Region,
            "--group-ids", $SecurityGroupId,
            "--output", "json"
        )
        $securityGroup = $securityGroup.SecurityGroups[0]
        Write-Success "Created security group: $SecurityGroupName ($SecurityGroupId)"
    }

    $rules = @(
        @{ IpProtocol = "tcp"; FromPort = 22; ToPort = 22; IpRanges = @(@{ CidrIp = $AllowedSshCidr; Description = "SSH" }) },
        @{ IpProtocol = "tcp"; FromPort = 80; ToPort = 80; IpRanges = @(@{ CidrIp = "0.0.0.0/0"; Description = "HTTP" }) }
    )

    if ($OpenHttps) {
        $rules += @{ IpProtocol = "tcp"; FromPort = 443; ToPort = 443; IpRanges = @(@{ CidrIp = "0.0.0.0/0"; Description = "HTTPS" }) }
    }

    $existingPermissions = @($securityGroup.IpPermissions)
    $missingRules = @()
    foreach ($rule in $rules) {
        $desiredCidr = $rule.IpRanges[0].CidrIp
        $match = $existingPermissions | Where-Object {
            $_.IpProtocol -eq $rule.IpProtocol -and
            [int]$_.FromPort -eq [int]$rule.FromPort -and
            [int]$_.ToPort -eq [int]$rule.ToPort -and
            (@($_.IpRanges) | Where-Object { $_.CidrIp -eq $desiredCidr }).Count -gt 0
        } | Select-Object -First 1

        if (-not $match) {
            $missingRules += $rule
        }
    }

    if ($missingRules.Count -eq 0) {
        Write-Info "Security group ingress already configured."
        return
    }

    $ruleFile = New-JsonTempFile -Value @($missingRules) -FilePrefix "axon-sg-ingress"
    try {
        Invoke-AwsText @(
            "ec2", "authorize-security-group-ingress",
            "--region", $Region,
            "--group-id", $SecurityGroupId,
            "--ip-permissions", "file://$ruleFile",
            "--output", "text"
        ) | Out-Null
        Write-Success "Configured missing ingress rules on security group."
    } catch {
        if ($_.Exception.Message -match 'InvalidPermission\.Duplicate') {
            Write-Info "Security group ingress rules already up to date."
        } else {
            throw
        }
    } finally {
        Remove-Item -LiteralPath $ruleFile -Force -ErrorAction SilentlyContinue
    }
}

function Get-UbuntuAmi {
    $ssmParameterName = if ($UseArm) {
        "/aws/service/canonical/ubuntu/server/22.04/stable/current/arm64/hvm/ebs-gp2/ami-id"
    } else {
        "/aws/service/canonical/ubuntu/server/22.04/stable/current/amd64/hvm/ebs-gp2/ami-id"
    }

    try {
        $amiId = Invoke-AwsText @(
            "ssm", "get-parameter",
            "--region", $Region,
            "--name", $ssmParameterName,
            "--query", "Parameter.Value",
            "--output", "text"
        )
        if (-not [string]::IsNullOrWhiteSpace($amiId)) {
            Write-Success "Using AMI from SSM: $amiId [$ssmParameterName]"
            return $amiId
        }
    } catch {
        Write-Info "SSM AMI lookup failed, falling back to direct image search."
    }

    $owner = "099720109477"
    $namePatterns = if ($UseArm) {
        @(
            "ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-arm64-server-*"
        )
    } else {
        @(
            "ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"
        )
    }

    foreach ($namePattern in $namePatterns) {
        $images = Invoke-AwsJson @(
            "ec2", "describe-images",
            "--region", $Region,
            "--owners", $owner,
            "--filters", "Name=name,Values=$namePattern", "Name=state,Values=available", "Name=virtualization-type,Values=hvm", "Name=root-device-type,Values=ebs",
            "--output", "json"
        )

        if ($images.Images -and $images.Images.Count -gt 0) {
            $latest = $images.Images | Sort-Object CreationDate | Select-Object -Last 1
            Write-Success "Using AMI: $($latest.ImageId) [$($latest.Name)]"
            return $latest.ImageId
        }
    }

    throw "No Ubuntu 22.04 image found in $Region via SSM or image search."
}

function New-UserDataFile {
    if ([string]::IsNullOrWhiteSpace($RepoUrl)) {
        return $null
    }

    $userData = @"
#!/bin/bash
set -e
apt-get update
apt-get install -y git
mkdir -p /opt
if [ ! -d /opt/axon ]; then
  git clone --depth 1 --branch $RepoBranch $RepoUrl /opt/axon
fi
chown -R ubuntu:ubuntu /opt/axon
cd /opt/axon
APP_USER=ubuntu ENABLE_WEB=1 ENABLE_NGINX=1 bash scripts/bootstrap-aws-free-tier.sh
"@

    $tempFile = [System.IO.Path]::Combine([System.IO.Path]::GetTempPath(), "axon-userdata.sh")
    Set-Content -Path $tempFile -Value $userData -NoNewline
    return $tempFile
}

function New-JsonTempFile {
    param(
        [Parameter(Mandatory = $true)]
        $Value,
        [string]$FilePrefix = "axon-json"
    )

    $tempFile = [System.IO.Path]::Combine(
        [System.IO.Path]::GetTempPath(),
        "$FilePrefix-$([guid]::NewGuid().ToString('N')).json"
    )
    ConvertTo-Json -InputObject $Value -Compress -Depth 8 | Set-Content -Path $tempFile -NoNewline
    return $tempFile
}

function Launch-Instance {
    $amiId = Get-UbuntuAmi
    $blockDeviceMappings = @(
        @{
            DeviceName = "/dev/sda1"
            Ebs = @{
                VolumeSize = $RootVolumeGiB
                VolumeType = "gp3"
                DeleteOnTermination = $true
            }
        }
    )
    $blockDeviceMappingsFile = New-JsonTempFile -Value $blockDeviceMappings -FilePrefix "axon-block-device-mappings"
    $tagSpec = "ResourceType=instance,Tags=[{Key=Name,Value=$InstanceName},{Key=Project,Value=Axon},{Key=RegionHint,Value=$Region}]"
    $volumeTagSpec = "ResourceType=volume,Tags=[{Key=Name,Value=$InstanceName-root},{Key=Project,Value=Axon}]"

    try {
        $args = @(
            "ec2", "run-instances",
            "--region", $Region,
            "--image-id", $amiId,
            "--instance-type", $InstanceType,
            "--key-name", $KeyPairName,
            "--security-group-ids", $SecurityGroupId,
            "--subnet-id", $SubnetId,
            "--associate-public-ip-address",
            "--metadata-options", "HttpTokens=required,HttpEndpoint=enabled",
            "--block-device-mappings", "file://$blockDeviceMappingsFile",
            "--tag-specifications", $tagSpec, $volumeTagSpec,
            "--count", "1",
            "--output", "json"
        )

        $userDataFile = New-UserDataFile
        if ($userDataFile) {
            $args += @("--user-data", "file://$userDataFile")
        }

        if ($DryRun) {
            $args += "--dry-run"
            try {
                Invoke-AwsText $args | Out-Null
            } catch {
                if ($_.Exception.Message -match "DryRunOperation") {
                    Write-Success "Dry run succeeded. AWS accepted the launch parameters."
                    return $null
                }
                throw
            }
            return $null
        }

        $runResult = Invoke-AwsJson $args
        return $runResult.Instances[0].InstanceId
    } finally {
        Remove-Item -LiteralPath $blockDeviceMappingsFile -Force -ErrorAction SilentlyContinue
        if ($userDataFile) {
            Remove-Item -LiteralPath $userDataFile -Force -ErrorAction SilentlyContinue
        }
    }
}

function Wait-And-Print {
    param([string]$InstanceId)

    if ($DryRun) {
        Write-Info "Dry run completed. No resources were created."
        return
    }

    Write-Info "Waiting for instance to enter running state..."
    Invoke-AwsText @("ec2", "wait", "instance-running", "--region", $Region, "--instance-ids", $InstanceId) | Out-Null

    $instance = Invoke-AwsJson @(
        "ec2", "describe-instances",
        "--region", $Region,
        "--instance-ids", $InstanceId,
        "--output", "json"
    )

    $details = $instance.Reservations[0].Instances[0]
    $publicIp = $details.PublicIpAddress
    $publicDns = $details.PublicDnsName

    Write-Success ""
    Write-Success "Axon EC2 instance created successfully"
    Write-Success "Region: $Region"
    Write-Success "Availability Zone: $AvailabilityZone"
    Write-Success "Instance ID: $InstanceId"
    Write-Success "Instance Type: $InstanceType"
    Write-Success "Public IP: $publicIp"
    Write-Success "Public DNS: $publicDns"
    Write-Success ""
    Write-Info "SSH command:"
    Write-Host "ssh -i $LocalKeyPath ubuntu@$publicIp"
    Write-Success ""
    if ([string]::IsNullOrWhiteSpace($RepoUrl)) {
        Write-Info "Next steps on the VM:"
        Write-Host "  1. Upload or clone the repo to /opt/axon"
        Write-Host "  2. Run: sudo APP_USER=ubuntu ENABLE_WEB=1 ENABLE_NGINX=1 bash /opt/axon/scripts/bootstrap-aws-free-tier.sh"
        Write-Host "  3. Edit /etc/axon/axon.env with Angel One credentials and web login"
        Write-Host "  4. Restart services: sudo systemctl restart axon-scheduler axon-web"
    } else {
        Write-Info "Repo bootstrap was passed via EC2 user-data. After 3-5 minutes, SSH in and update /etc/axon/axon.env before enabling live trading."
    }

    return [pscustomobject]@{
        Region = $Region
        AvailabilityZone = $AvailabilityZone
        InstanceId = $InstanceId
        InstanceType = $InstanceType
        PublicIp = $publicIp
        PublicDns = $publicDns
        KeyPath = $LocalKeyPath
        SecurityGroupId = $SecurityGroupId
        VpcId = $VpcId
        SubnetId = $SubnetId
        RepoBootstrap = -not [string]::IsNullOrWhiteSpace($RepoUrl)
    }
}

Write-Success "========================================"
Write-Success "Axon - AWS EC2 Mumbai Deployment"
Write-Success "========================================"

Resolve-AwsCliPath | Out-Null

try {
    $identity = Invoke-AwsJson @("sts", "get-caller-identity", "--output", "json")
    Write-Success "Using AWS account: $($identity.Account)"

    if ([string]::IsNullOrWhiteSpace($AllowedSshCidr)) {
        $AllowedSshCidr = Get-PublicIpCidr
    }

    if ($UseArm -and $InstanceType -eq "t3.micro") {
        $InstanceType = "t4g.micro"
    }

    Write-Info "Target region: $Region"
    Write-Info "Recommended stable instance for this repo: t3.micro (x86_64)"
    if ($UseArm) {
        Write-Info "ARM mode enabled. Using $InstanceType for lower cost, with slightly higher package compatibility risk."
    }

    Ensure-KeyPair
    Resolve-VpcAndSubnet
    Ensure-SecurityGroup
    $instanceId = Launch-Instance
    $result = Wait-And-Print -InstanceId $instanceId
    if ($PassThru -and $result) {
        return $result
    }
} catch {
    Write-Err $_.Exception.Message
    throw
}