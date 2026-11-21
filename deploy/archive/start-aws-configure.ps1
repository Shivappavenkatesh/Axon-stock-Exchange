# Axon - AWS CLI Configuration Helper

param(
    [switch]$UseSso,
    [string]$Region = "ap-south-1",
    [string]$OutputFormat = "json",
    [string]$ProfileName = "default"
)

$ErrorActionPreference = "Stop"

function Resolve-AwsCliPath {
    $command = Get-Command aws -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    $fallback = "C:\Program Files\Amazon\AWSCLIV2\aws.exe"
    if (Test-Path $fallback) {
        return $fallback
    }

    throw "AWS CLI v2 is not installed."
}

$awsCli = Resolve-AwsCliPath

& $awsCli configure set region $Region --profile $ProfileName
& $awsCli configure set output $OutputFormat --profile $ProfileName

Write-Host "AWS CLI defaults set:" -ForegroundColor Green
Write-Host "  Region: $Region"
Write-Host "  Output: $OutputFormat"
Write-Host "  Profile: $ProfileName"
Write-Host ""

if ($UseSso) {
    Write-Host "Use your AWS IAM Identity Center access portal URL as the SSO start URL." -ForegroundColor Yellow
    Write-Host "Valid example: https://your-company.awsapps.com/start" -ForegroundColor Yellow
    Write-Host "Do not use https://console.aws.amazon.com/ as the SSO start URL." -ForegroundColor Yellow
    Write-Host "The SSO region is the IAM Identity Center region, which may differ from the EC2 region ap-south-1." -ForegroundColor Yellow
    Write-Host "" 
    Write-Host "Starting AWS SSO configuration..." -ForegroundColor Yellow
    & $awsCli configure sso --profile $ProfileName
    Write-Host "Starting AWS SSO login..." -ForegroundColor Yellow
    & $awsCli sso login --profile $ProfileName
    Write-Host "" 
    Write-Host "Use this profile for future commands:" -ForegroundColor Green
    Write-Host "  `$env:AWS_PROFILE = '$ProfileName'"
} else {
    Write-Host "Starting AWS access-key configuration..." -ForegroundColor Yellow
    & $awsCli configure --profile $ProfileName
}