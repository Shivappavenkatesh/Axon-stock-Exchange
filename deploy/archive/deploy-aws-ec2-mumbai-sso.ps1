# Axon - AWS EC2 Mumbai Deployment via SSO + SSM
# Launches a keyless EC2 instance in ap-south-1 using an SSM-managed IAM role.

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
    [string]$InstanceProfileName = "axon-ssm-ec2-profile",
    [string]$IamRoleName = "axon-ssm-ec2-role",
    [switch]$DryRun,
    [switch]$PassThru
)

$ErrorActionPreference = "Stop"
$script:AwsCliPath = $null

function Write-Success { param($m) Write-Host $m -ForegroundColor Green }
function Write-Info    { param($m) Write-Host $m -ForegroundColor Yellow }
function Write-Err     { param($m) Write-Host $m -ForegroundColor Red }

function Resolve-AwsCliPath {
    if ($script:AwsCliPath) { return $script:AwsCliPath }
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
    }
}

function New-JsonTempFile {
    param(
        [Parameter(Mandatory = $true)]
        $Value,
        [string]$FilePrefix = "axon-json"
    )

    $tempFile = [System.IO.Path]::Combine([System.IO.Path]::GetTempPath(), "$FilePrefix-$([guid]::NewGuid().ToString('N')).json")
    ConvertTo-Json -InputObject $Value -Compress -Depth 8 | Set-Content -Path $tempFile -NoNewline
    return $tempFile
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
            "--description", "Axon EC2 access for web via SSM-managed instance",
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
        if (-not $match) { $missingRules += $rule }
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
    } finally {
        Remove-Item -LiteralPath $ruleFile -Force -ErrorAction SilentlyContinue
    }
}

function Ensure-SsmRoleAndProfile {
    $trustPolicy = '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}'

    $roleExists = $true
    try {
        Invoke-AwsJson @("iam", "get-role", "--role-name", $IamRoleName, "--output", "json") | Out-Null
    } catch {
        $roleExists = $false
    }

    if (-not $roleExists) {
        Write-Info "Creating IAM role for SSM-managed EC2 access."
        Invoke-AwsJson @(
            "iam", "create-role",
            "--role-name", $IamRoleName,
            "--assume-role-policy-document", $trustPolicy,
            "--output", "json"
        ) | Out-Null
    } else {
        Write-Info "Reusing IAM role: $IamRoleName"
    }

    Invoke-AwsText @(
        "iam", "attach-role-policy",
        "--role-name", $IamRoleName,
        "--policy-arn", "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
    ) | Out-Null

    $profileExists = $true
    try {
        Invoke-AwsJson @("iam", "get-instance-profile", "--instance-profile-name", $InstanceProfileName, "--output", "json") | Out-Null
    } catch {
        $profileExists = $false
    }

    if (-not $profileExists) {
        Write-Info "Creating instance profile: $InstanceProfileName"
        Invoke-AwsJson @("iam", "create-instance-profile", "--instance-profile-name", $InstanceProfileName, "--output", "json") | Out-Null
        Start-Sleep -Seconds 3
    } else {
        Write-Info "Reusing instance profile: $InstanceProfileName"
    }

    try {
        Invoke-AwsText @(
            "iam", "add-role-to-instance-profile",
            "--instance-profile-name", $InstanceProfileName,
            "--role-name", $IamRoleName
        ) | Out-Null
    } catch {
        if ($_.Exception.Message -notmatch "LimitExceeded|EntityAlreadyExists|already") {
            throw
        }
    }

    $script:InstanceProfileName = $InstanceProfileName
}

function Get-UbuntuAmi {
    $ssmParameterName = if ($UseArm) {
        "/aws/service/canonical/ubuntu/server/22.04/stable/current/arm64/hvm/ebs-gp2/ami-id"
    } else {
        "/aws/service/canonical/ubuntu/server/22.04/stable/current/amd64/hvm/ebs-gp2/ami-id"
    }
    $amiId = Invoke-AwsText @(
        "ssm", "get-parameter",
        "--region", $Region,
        "--name", $ssmParameterName,
        "--query", "Parameter.Value",
        "--output", "text"
    )
    if ([string]::IsNullOrWhiteSpace($amiId)) {
        throw "Could not resolve Ubuntu AMI from $ssmParameterName"
    }
    Write-Success "Using AMI from SSM: $amiId [$ssmParameterName]"
    return $amiId
}

function New-UserDataFile {
    $userData = @'
#!/bin/bash
set -e
snap install amazon-ssm-agent --classic || true
systemctl enable snap.amazon-ssm-agent.amazon-ssm-agent.service || true
systemctl restart snap.amazon-ssm-agent.amazon-ssm-agent.service || true
'@
    $tempFile = [System.IO.Path]::Combine([System.IO.Path]::GetTempPath(), "axon-userdata-ssm.sh")
    Set-Content -Path $tempFile -Value $userData -NoNewline
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
    $userDataFile = New-UserDataFile
    $tagSpec = "ResourceType=instance,Tags=[{Key=Name,Value=$InstanceName},{Key=Project,Value=Axon},{Key=AccessMode,Value=SSM}]"
    $volumeTagSpec = "ResourceType=volume,Tags=[{Key=Name,Value=$InstanceName-root},{Key=Project,Value=Axon}]"

    try {
        $args = @(
            "ec2", "run-instances",
            "--region", $Region,
            "--image-id", $amiId,
            "--instance-type", $InstanceType,
            "--iam-instance-profile", "Name=$InstanceProfileName",
            "--security-group-ids", $SecurityGroupId,
            "--subnet-id", $SubnetId,
            "--associate-public-ip-address",
            "--metadata-options", "HttpTokens=required,HttpEndpoint=enabled",
            "--block-device-mappings", "file://$blockDeviceMappingsFile",
            "--user-data", "file://$userDataFile",
            "--tag-specifications", $tagSpec, $volumeTagSpec,
            "--count", "1",
            "--output", "json"
        )

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
        Remove-Item -LiteralPath $userDataFile -Force -ErrorAction SilentlyContinue
    }
}

function Wait-ForSsmManagedInstance {
    param([string]$InstanceId)

    Write-Info "Waiting for instance to enter running state..."
    Invoke-AwsText @("ec2", "wait", "instance-running", "--region", $Region, "--instance-ids", $InstanceId) | Out-Null

    for ($attempt = 1; $attempt -le 30; $attempt++) {
        $managed = Invoke-AwsJson @(
            "ssm", "describe-instance-information",
            "--region", $Region,
            "--filters", "Key=InstanceIds,Values=$InstanceId",
            "--output", "json"
        )
        if ($managed.InstanceInformationList -and $managed.InstanceInformationList.Count -gt 0) {
            return $managed.InstanceInformationList[0].InstanceId
        }
        Start-Sleep -Seconds 10
    }

    throw "Instance $InstanceId did not register with AWS Systems Manager in time."
}

function Wait-And-Print {
    param([string]$InstanceId)

    if ($DryRun) {
        Write-Info "Dry run completed. No resources were created."
        return
    }

    $managedInstanceId = Wait-ForSsmManagedInstance -InstanceId $InstanceId
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
    Write-Success "Managed Instance ID: $managedInstanceId"
    Write-Success "Instance Type: $InstanceType"
    Write-Success "Public IP: $publicIp"
    Write-Success "Public DNS: $publicDns"
    Write-Success ""

    return [pscustomobject]@{
        Region = $Region
        AvailabilityZone = $AvailabilityZone
        InstanceId = $InstanceId
        ManagedInstanceId = $managedInstanceId
        InstanceType = $InstanceType
        PublicIp = $publicIp
        PublicDns = $publicDns
        SecurityGroupId = $SecurityGroupId
        VpcId = $VpcId
        SubnetId = $SubnetId
        InstanceProfileName = $InstanceProfileName
    }
}

Write-Success "========================================"
Write-Success "Axon - AWS EC2 Mumbai SSO/SSM Deployment"
Write-Success "========================================"

Resolve-AwsCliPath | Out-Null

try {
    $identity = Invoke-AwsJson @("sts", "get-caller-identity", "--output", "json")
    Write-Success "Using AWS account: $($identity.Account)"

    if ($UseArm -and $InstanceType -eq "t3.micro") {
        $InstanceType = "t4g.micro"
    }

    Write-Info "Target region: $Region"
    Write-Info "Using SSO + SSM keyless access. No EC2 key pair will be created or stored."

    Resolve-VpcAndSubnet
    Ensure-SecurityGroup
    Ensure-SsmRoleAndProfile
    $instanceId = Launch-Instance
    $result = Wait-And-Print -InstanceId $instanceId
    if ($PassThru -and $result) {
        return $result
    }
} catch {
    Write-Err $_.Exception.Message
    throw
}