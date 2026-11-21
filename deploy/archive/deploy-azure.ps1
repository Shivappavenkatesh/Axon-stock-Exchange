# Axon Aone - Azure Container Instances Deployment Script (PowerShell)
# Deploys the trading scheduler to Azure Container Instances

param(
    [string]$ResourceGroup = "axon-aone-rg",
    [string]$Location = "southindia",
    [string]$RegistryName = "axonaoneacr",
    [string]$ContainerGroup = "axon-aone-aci",
    [string]$ImageName = "axon-aone",
    [string]$SubscriptionId = "",
    [string]$ApiKey = $env:ANGEL_ONE_API_KEY,
    [string]$ClientId = $env:ANGEL_ONE_CLIENT_ID,
    [string]$Pin = $env:ANGEL_ONE_PIN,
    [string]$TotpSecret = $env:ANGEL_ONE_TOTP_SECRET,
    [string]$MockMode = "false"
)

$ErrorActionPreference = "Stop"

function Write-Success {
    param($m)
    Write-Host $m -ForegroundColor Green
}

function Write-Info {
    param($m)
    Write-Host $m -ForegroundColor Yellow
}

function Write-Err {
    param($m)
    Write-Host $m -ForegroundColor Red
}

Write-Success "========================================"
Write-Success "Axon Aone - Azure ACI Deployment"
Write-Success "========================================"

# Check prerequisites
Write-Info "`nChecking prerequisites..."

if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    Write-Err "Azure CLI is not installed. Download: https://docs.microsoft.com/cli/azure/"
    exit 1
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Err "Docker is not installed. Download: https://www.docker.com/products/docker-desktop"
    exit 1
}

Write-Success "OK - Prerequisites check passed"

# Login to Azure
Write-Info "`nLogging in to Azure..."
az login | Out-Null

if ($SubscriptionId) {
    Write-Info "Setting subscription..."
    az account set --subscription $SubscriptionId
}

# Create resource group
Write-Info "`nCreating resource group: $ResourceGroup"
az group create --name $ResourceGroup --location $Location | Out-Null
Write-Success "OK - Resource group created"

# Create container registry
Write-Info "`nCreating container registry: $RegistryName"
az acr create --resource-group $ResourceGroup --name $RegistryName --sku Basic | Out-Null
Write-Success "OK - Container registry created"

# Build and push Docker image
Write-Info "`nBuilding and pushing Docker image..."
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$latestTag = $ImageName + ":latest"
$timestampTag = $ImageName + ":" + $timestamp
az acr build --registry $RegistryName --image $latestTag --image $timestampTag . | Out-Null
Write-Success "OK - Docker image built and pushed"

# Get registry credentials
Write-Info "`nGetting registry credentials..."
$registryUser = az acr credential show --name $RegistryName --query username -o tsv
$registryPassword = az acr credential show --name $RegistryName --query "passwords[0].value" -o tsv
$registryUrl = "$RegistryName.azurecr.io"

# Validate credentials
Write-Info "`nChecking Angel One credentials..."

if ([string]::IsNullOrEmpty($ApiKey)) {
    $ApiKey = Read-Host "Enter Angel One API Key"
}

if ([string]::IsNullOrEmpty($ClientId)) {
    $ClientId = Read-Host "Enter Angel One Client ID"
}

if ([string]::IsNullOrEmpty($Pin)) {
    $Pin = Read-Host "Enter Angel One PIN"
}

if ([string]::IsNullOrEmpty($TotpSecret)) {
    $TotpSecret = Read-Host "Enter Angel One TOTP Secret"
}

$missingCreds = [string]::IsNullOrEmpty($ApiKey) -or [string]::IsNullOrEmpty($ClientId) -or [string]::IsNullOrEmpty($Pin) -or [string]::IsNullOrEmpty($TotpSecret)
if ($missingCreds) {
    Write-Err "All Angel One credentials are required: API Key, Client ID, PIN, TOTP Secret"
    exit 1
}

Write-Success "OK - Credentials captured"

# Create container instance
Write-Info "`nCreating container instance: $ContainerGroup"

$imageFullPath = "$registryUrl/$ImageName:latest"

az container create --resource-group $ResourceGroup --name $ContainerGroup --image $imageFullPath `
    --registry-login-server $registryUrl --registry-username $registryUser --registry-password $registryPassword `
    --environment-variables "ANGEL_ONE_API_KEY=$ApiKey" "ANGEL_ONE_CLIENT_ID=$ClientId" "ANGEL_ONE_PIN=$Pin" "ANGEL_ONE_TOTP_SECRET=$TotpSecret" "MOCK_MODE=$MockMode" "TZ=Asia/Kolkata" "PYTHONUNBUFFERED=1" `
    --memory 2 --cpu 1 --restart-policy Always --command-line "python run_trader.py --schedule" --ports 8080 | Out-Null

Write-Success "OK - Container instance created"

# Wait for container
Write-Info "`nWaiting for container to be ready..."
Start-Sleep -Seconds 10

# Check status
Write-Info "`nContainer Status:"
az container show `
    --resource-group $ResourceGroup `
    --name $ContainerGroup `
    --query "{ Name: name, State: containers[0].instanceView.currentState.state }" `
    -o table

Write-Info "`nRecent Logs:"
az container logs --resource-group $ResourceGroup --name $ContainerGroup --tail 20

Write-Success "`n========================================"
Write-Success "Deployment Complete!"
Write-Success "========================================"
Write-Info "Resource Group: $ResourceGroup"
Write-Info "Container: $ContainerGroup"
Write-Info "Registry: $registryUrl"
Write-Info ""
Write-Info "View logs:"
Write-Info "  az container logs --resource-group $ResourceGroup --name $ContainerGroup -f"
Write-Info ""
Write-Info "Restart:"
Write-Info "  az container restart --resource-group $ResourceGroup --name $ContainerGroup"
Write-Info ""
Write-Info "Delete:"
Write-Info "  az group delete --name $ResourceGroup --yes"
