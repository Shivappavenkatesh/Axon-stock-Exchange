# Axon Aone - Azure B1s VM Deployment Script (PowerShell)
# Deploys the trading scheduler to an Ubuntu B1s VM in South India

param(
    [string]$ResourceGroup = "axon-aone-rg",
    [string]$Location = "southindia",
    [string]$RegistryName = "axonaoneacr",
    [string]$ImageName = "axon-aone",
    [string]$VmName = "axon-aone-vm",
    [string]$VmSize = "Standard_D2s_v3",
    [string]$SubscriptionId = "",
    [string]$ApiKey = $env:ANGEL_ONE_API_KEY,
    [string]$ClientId = $env:ANGEL_ONE_CLIENT_ID,
    [string]$Pin = $env:ANGEL_ONE_PIN,
    [string]$TotpSecret = $env:ANGEL_ONE_TOTP_SECRET,
    [string]$MockMode = "false"
)

$ErrorActionPreference = "Stop"

function Write-Success { param($m) Write-Host $m -ForegroundColor Green }
function Write-Info    { param($m) Write-Host $m -ForegroundColor Yellow }
function Write-Err     { param($m) Write-Host $m -ForegroundColor Red }

Write-Success "========================================"
Write-Success "Axon Aone - Azure B1s VM Deployment"
Write-Success "========================================"

# Prerequisites
Write-Info "`nChecking prerequisites..."
if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    Write-Err "Azure CLI (az) is not installed."
    exit 1
}
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Err "Docker is not installed or not on PATH. Please install/start Docker Desktop first."
    exit 1
}
Write-Success "OK - Azure CLI and Docker found"

# Azure login
Write-Info "`nLogging in to Azure..."
az login | Out-Null

if ($SubscriptionId) {
    Write-Info "Setting subscription: $SubscriptionId"
    az account set --subscription $SubscriptionId
}

$currentSub = az account show --query id -o tsv
Write-Success "Using subscription: $currentSub"

# Resource group
Write-Info "`nEnsuring resource group exists: $ResourceGroup ($Location)"
az group create --name $ResourceGroup --location $Location | Out-Null
Write-Success "OK - Resource group ready"

# Container registry
Write-Info "`nEnsuring container registry exists: $RegistryName"
$acrExists = $false
az acr show --name $RegistryName --resource-group $ResourceGroup 1>$null 2>$null
if ($LASTEXITCODE -eq 0) {
    $acrExists = $true
}

if (-not $acrExists) {
    az acr create --resource-group $ResourceGroup --name $RegistryName --sku Basic | Out-Null
    Write-Success "OK - Created ACR: $RegistryName"
} else {
    Write-Info "ACR already exists, reusing: $RegistryName"
}

# Ensure admin user is enabled
Write-Info "Enabling admin user on ACR..."
az acr update --resource-group $ResourceGroup --name $RegistryName --admin-enabled true | Out-Null
Write-Success "OK - ACR admin user enabled"

# Build & push image
Write-Info "`nBuilding Docker image and pushing to ACR..."
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"

Write-Info "Logging in to ACR..."
az acr login --name $RegistryName | Out-Null

$registryUrl = "$RegistryName.azurecr.io"
$latestTag = "$registryUrl/${ImageName}:latest"
$versionTag = "$registryUrl/${ImageName}:$timestamp"

docker build -t $latestTag .
docker tag $latestTag $versionTag
docker push $latestTag
docker push $versionTag

Write-Success "OK - Image built and pushed: $latestTag"

# Registry credentials
Write-Info "`nFetching registry credentials..."
$registryUser = az acr credential show --name $RegistryName --query username -o tsv
$registryPassword = az acr credential show --name $RegistryName --query "passwords[0].value" -o tsv
Write-Success "OK - Registry URL: $registryUrl"

# API credentials - prompt if not provided
Write-Info "`nChecking Angel One credentials..."
if ([string]::IsNullOrWhiteSpace($ApiKey)) {
    $ApiKey = Read-Host "Enter Angel One API Key"
}
if ([string]::IsNullOrWhiteSpace($ClientId)) {
    $ClientId = Read-Host "Enter Angel One Client ID (e.g., ADCE701334)"
}
if ([string]::IsNullOrWhiteSpace($Pin)) {
    $Pin = Read-Host "Enter Angel One PIN (4-digit MPIN)"
}
if ([string]::IsNullOrWhiteSpace($TotpSecret)) {
    $TotpSecret = Read-Host "Enter Angel One TOTP Secret (base32 format)"
}

if ([string]::IsNullOrWhiteSpace($ApiKey) -or [string]::IsNullOrWhiteSpace($ClientId) -or
    [string]::IsNullOrWhiteSpace($Pin) -or [string]::IsNullOrWhiteSpace($TotpSecret)) {
    Write-Err "All Angel One credentials are required (API Key, Client ID, PIN, TOTP Secret)"
    exit 1
}
Write-Success "OK - Credentials captured"

# VM
Write-Info "`nEnsuring B1s Ubuntu VM exists: $VmName ($Location)"
$vmExists = $false
try {
    az vm show -g $ResourceGroup -n $VmName 1>$null 2>$null
    $vmExists = $true
} catch {
    $vmExists = $false
}

if (-not $vmExists) {
    Write-Info "VM not found, creating new B1s Ubuntu VM..."
    az vm create `
      --resource-group $ResourceGroup `
      --name $VmName `
      --image Ubuntu2204 `
      --size $VmSize `
      --admin-username azureuser `
      --generate-ssh-keys `
      --public-ip-sku Standard `
      --location $Location
    Write-Success "OK - VM created: $VmName"
} else {
    Write-Info "VM already exists, reusing: $VmName"
}

# Public IP
$publicIp = az vm show -d -g $ResourceGroup -n $VmName --query publicIps -o tsv
Write-Success "VM public IP: $publicIp"

# Remote script to install Docker and run container
Write-Info "`nConfiguring VM (install Docker and run container)..."
$remoteScript = @'
#!/bin/bash
set -e

REGISTRY_URL="$1"
REGISTRY_USER="$2"
REGISTRY_PASSWORD="$3"
API_KEY="$4"
CLIENT_ID="$5"
PIN="$6"
TOTP_SECRET="$7"
MOCK_MODE="$8"
IMAGE_NAME="$9"

sudo apt-get update
sudo apt-get install -y docker.io
sudo systemctl enable docker
sudo systemctl start docker

sudo docker login "$REGISTRY_URL" -u "$REGISTRY_USER" -p "$REGISTRY_PASSWORD"

sudo docker rm -f axon-aone || true

sudo docker run -d --name axon-aone \
    --restart unless-stopped \
    -e ANGEL_ONE_API_KEY="$API_KEY" \
    -e ANGEL_ONE_CLIENT_ID="$CLIENT_ID" \
    -e ANGEL_ONE_PIN="$PIN" \
    -e ANGEL_ONE_TOTP_SECRET="$TOTP_SECRET" \
    -e MOCK_MODE="$MOCK_MODE" \
    -e TZ="Asia/Kolkata" \
    -e PYTHONUNBUFFERED="1" \
    "$REGISTRY_URL/$IMAGE_NAME:latest" \
    python run_trader.py --schedule
'@

az vm run-command invoke `
  --resource-group $ResourceGroup `
  --name $VmName `
  --command-id RunShellScript `
  --scripts $remoteScript `
  --parameters $registryUrl $registryUser $registryPassword $ApiKey $ClientId $Pin $TotpSecret $MockMode $ImageName | Out-Null

Write-Success "OK - VM configured and container started"

Write-Success "`n========================================"
Write-Success "Deployment Complete!"
Write-Success "========================================"
Write-Info    "VM Name:     $VmName"
Write-Info    "ResourceGrp: $ResourceGroup"
Write-Info    "Region:      $Location"
Write-Info    "VM Size:     $VmSize"
Write-Info    "Registry:    $registryUrl"
Write-Info    "Public IP:   $publicIp"
Write-Info ""
Write-Info "To SSH into the VM:"
Write-Info "  ssh azureuser@$publicIp"
Write-Info ""
Write-Info "To view container logs (after SSH):"
Write-Info "  sudo docker logs -f axon-aone"
Write-Info ""
Write-Info "To restart the container:"
Write-Info "  sudo docker restart axon-aone"
