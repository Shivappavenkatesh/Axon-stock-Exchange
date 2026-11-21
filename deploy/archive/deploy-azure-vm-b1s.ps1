# Axon Capital Engine - Azure VM Deployment Script (PowerShell)
# Deploys the trading scheduler to an Ubuntu VM in South India

param(
    [string]$ResourceGroup = "axon-aone-rg",
    [string]$Location = "southindia",
    [string]$RegistryName = "axonaoneacr",
    [string]$ImageName = "axon",
    [string]$VmName = "axon-aone-vm",
    [string]$VmSize = "Standard_D2s_v3",
    [string]$SubscriptionId = "",
    [string]$ApiKey = $env:ANGEL_ONE_API_KEY,
    [string]$ClientId = $env:ANGEL_ONE_CLIENT_ID,
    [string]$Pin = $env:ANGEL_ONE_PIN,
    [string]$TotpSecret = $env:ANGEL_ONE_TOTP_SECRET,
    [double]$LtpMinIntervalSec = $(if ($env:ANGEL_ONE_LTP_MIN_INTERVAL_SEC) { [double]$env:ANGEL_ONE_LTP_MIN_INTERVAL_SEC } else { 0.35 }),
    [double]$CandleMinIntervalSec = $(if ($env:ANGEL_ONE_CANDLE_MIN_INTERVAL_SEC) { [double]$env:ANGEL_ONE_CANDLE_MIN_INTERVAL_SEC } else { 1.50 }),
    [int]$TooManyRequestsMaxRetries = $(if ($env:ANGEL_ONE_TOO_MANY_REQUESTS_MAX_RETRIES) { [int]$env:ANGEL_ONE_TOO_MANY_REQUESTS_MAX_RETRIES } else { 5 }),
    [int]$CandleTooManyRequestsMaxRetries = $(if ($env:ANGEL_ONE_CANDLE_TOO_MANY_REQUESTS_MAX_RETRIES) { [int]$env:ANGEL_ONE_CANDLE_TOO_MANY_REQUESTS_MAX_RETRIES } else { 3 }),
    [double]$TooManyRequestsBackoffBaseSec = $(if ($env:ANGEL_ONE_TOO_MANY_REQUESTS_BACKOFF_BASE_SEC) { [double]$env:ANGEL_ONE_TOO_MANY_REQUESTS_BACKOFF_BASE_SEC } else { 1.0 }),
    [double]$TooManyRequestsBackoffMaxSec = $(if ($env:ANGEL_ONE_TOO_MANY_REQUESTS_BACKOFF_MAX_SEC) { [double]$env:ANGEL_ONE_TOO_MANY_REQUESTS_BACKOFF_MAX_SEC } else { 30.0 }),
    [int]$MarketScanBatchSize = $(if ($env:AXON_MARKET_SCAN_BATCH_SIZE) { [int]$env:AXON_MARKET_SCAN_BATCH_SIZE } else { 18 }),
    [switch]$UseAcrBuild,
    [switch]$SkipDockerLogin
)

$ErrorActionPreference = "Stop"

function Write-Success { param($m) Write-Host $m -ForegroundColor Green }
function Write-Info    { param($m) Write-Host $m -ForegroundColor Yellow }
function Write-Err     { param($m) Write-Host $m -ForegroundColor Red }

Write-Success "========================================"
Write-Success "Axon - Azure VM Deployment"
Write-Success "========================================"

# Prerequisites
Write-Info "`nChecking prerequisites..."
if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    Write-Err "Azure CLI (az) is not installed."
    exit 1
}
if (-not $UseAcrBuild) {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Write-Err "Docker is not installed or not on PATH. Please install/start Docker Desktop first (or use -UseAcrBuild)."
        exit 1
    }
}
Write-Success "OK - Azure CLI ready"
if (-not $UseAcrBuild) {
    Write-Success "OK - Docker found"
} else {
    Write-Info "Using ACR build (Docker not required locally)."
}

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
try {
    az acr show --name $RegistryName --resource-group $ResourceGroup 1>$null 2>$null
    if ($LASTEXITCODE -eq 0) {
        $acrExists = $true
    }
} catch {
    $acrExists = $false
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

$registryUrl = "$RegistryName.azurecr.io"

$latestTag = "$registryUrl/${ImageName}:latest"
$versionTag = "$registryUrl/${ImageName}:$timestamp"

if ($UseAcrBuild) {
    Write-Info "Building inside Azure ACR (this avoids local Docker Hub pulls)..."
    az acr build `
        --resource-group $ResourceGroup `
        --registry $RegistryName `
        --image "${ImageName}:latest" `
        --image "${ImageName}:$timestamp" `
        . | Out-Null
    Write-Success "OK - Image built in ACR: $latestTag"
} else {
    Write-Info "Fetching ACR credentials for Docker login..."
    $registryUser = az acr credential show --name $RegistryName --query username -o tsv
    $registryPassword = az acr credential show --name $RegistryName --query "passwords[0].value" -o tsv

    if (-not $SkipDockerLogin) {
        Write-Info "Logging in to ACR via docker login (password-stdin)..."
        $registryPassword | docker login $registryUrl -u $registryUser --password-stdin | Out-Null
    } else {
        Write-Info "Skipping docker login (SkipDockerLogin switch is set)."
    }

    docker build -t $latestTag .
    docker tag $latestTag $versionTag
    docker push $latestTag
    docker push $versionTag

    Write-Success "OK - Image built and pushed: $latestTag"
}

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
Write-Info "`nEnsuring Ubuntu VM exists: $VmName ($Location)"
$vmExists = $false
try {
    az vm show -g $ResourceGroup -n $VmName 1>$null 2>$null
    $vmExists = $true
} catch {
    $vmExists = $false
}

if (-not $vmExists) {
    Write-Info "VM not found, creating new Ubuntu VM..."
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

# Open port 8501 for the Streamlit dashboard
Write-Info "`nOpening port 8501 for Streamlit dashboard..."
az vm open-port `
    --resource-group $ResourceGroup `
    --name $VmName `
    --port 8501 `
    --priority 1010 | Out-Null
Write-Success "OK - Port 8501 opened for dashboard access"

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
IMAGE_NAME="$8"
LTP_MIN_INTERVAL_SEC="$9"
CANDLE_MIN_INTERVAL_SEC="${10}"
TOO_MANY_MAX_RETRIES="${11}"
CANDLE_TOO_MANY_MAX_RETRIES="${12}"
TOO_MANY_BACKOFF_BASE_SEC="${13}"
TOO_MANY_BACKOFF_MAX_SEC="${14}"
MARKET_SCAN_BATCH_SIZE="${15}"

sudo apt-get update
sudo apt-get install -y docker.io
sudo systemctl enable docker
sudo systemctl start docker

sudo docker login "$REGISTRY_URL" -u "$REGISTRY_USER" -p "$REGISTRY_PASSWORD"
NETWORK_NAME="axon-network"
DB_CONTAINER_NAME="axon-postgres"
DB_NAME="axon"
DB_USER="axon"
DB_PASSWORD="axon_password"
DB_HOST="$DB_CONTAINER_NAME"
DB_URL="postgresql+psycopg2://$DB_USER:$DB_PASSWORD@$DB_HOST:5432/$DB_NAME"

sudo docker rm -f "$DB_CONTAINER_NAME" || true
sudo docker rm -f axon-scheduler || true
sudo docker rm -f axon-dashboard || true

sudo docker network create "$NETWORK_NAME" || true
sudo docker volume create axon-postgres-data || true

sudo docker run -d --name "$DB_CONTAINER_NAME" \
    --restart unless-stopped \
    --network "$NETWORK_NAME" \
    -e POSTGRES_DB="$DB_NAME" \
    -e POSTGRES_USER="$DB_USER" \
    -e POSTGRES_PASSWORD="$DB_PASSWORD" \
    -v axon-postgres-data:/var/lib/postgresql/data \
    postgres:15

for attempt in $(seq 1 30); do
    if sudo docker exec "$DB_CONTAINER_NAME" pg_isready -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1; then
        break
    fi

    if [ "$attempt" -eq 30 ]; then
        echo "PostgreSQL did not become ready in time" >&2
        sudo docker logs "$DB_CONTAINER_NAME" || true
        exit 1
    fi

    sleep 2
done

sudo docker run -d --name axon-scheduler \
    --restart unless-stopped \
    --network "$NETWORK_NAME" \
    -e AXON_TRADE_MODE="LIVE" \
    -e ANGEL_ONE_API_KEY="$API_KEY" \
    -e ANGEL_ONE_CLIENT_ID="$CLIENT_ID" \
    -e ANGEL_ONE_PIN="$PIN" \
    -e ANGEL_ONE_TOTP_SECRET="$TOTP_SECRET" \
    -e ANGEL_ONE_LTP_MIN_INTERVAL_SEC="$LTP_MIN_INTERVAL_SEC" \
    -e ANGEL_ONE_CANDLE_MIN_INTERVAL_SEC="$CANDLE_MIN_INTERVAL_SEC" \
    -e ANGEL_ONE_INTRADAY_LOOKBACK_DAYS="1" \
    -e ANGEL_ONE_INTRADAY_INTERVAL_MINUTES="5" \
    -e ANGEL_ONE_CANDLE_TOO_MANY_REQUESTS_MAX_RETRIES="$CANDLE_TOO_MANY_MAX_RETRIES" \
    -e ANGEL_ONE_CANDLE_CACHE_TTL_SEC="330" \
    -e ANGEL_ONE_TOO_MANY_REQUESTS_MAX_RETRIES="$TOO_MANY_MAX_RETRIES" \
    -e ANGEL_ONE_TOO_MANY_REQUESTS_BACKOFF_BASE_SEC="$TOO_MANY_BACKOFF_BASE_SEC" \
    -e ANGEL_ONE_TOO_MANY_REQUESTS_BACKOFF_MAX_SEC="$TOO_MANY_BACKOFF_MAX_SEC" \
    -e AXON_MARKET_SCAN_BATCH_SIZE="$MARKET_SCAN_BATCH_SIZE" \
    -e AXON_DATABASE_URL="$DB_URL" \
    -e TZ="Asia/Kolkata" \
    -e PYTHONUNBUFFERED="1" \
    "$REGISTRY_URL/$IMAGE_NAME:latest" \
    python run_trader.py --schedule --angel-one

sudo docker run -d --name axon-dashboard \
    --restart unless-stopped \
    --network "$NETWORK_NAME" \
    -p 8501:8501 \
    -e AXON_TRADE_MODE="LIVE" \
    -e ANGEL_ONE_API_KEY="$API_KEY" \
    -e ANGEL_ONE_CLIENT_ID="$CLIENT_ID" \
    -e ANGEL_ONE_PIN="$PIN" \
    -e ANGEL_ONE_TOTP_SECRET="$TOTP_SECRET" \
    -e ANGEL_ONE_LTP_MIN_INTERVAL_SEC="$LTP_MIN_INTERVAL_SEC" \
    -e ANGEL_ONE_CANDLE_MIN_INTERVAL_SEC="$CANDLE_MIN_INTERVAL_SEC" \
    -e ANGEL_ONE_INTRADAY_LOOKBACK_DAYS="1" \
    -e ANGEL_ONE_INTRADAY_INTERVAL_MINUTES="5" \
    -e ANGEL_ONE_CANDLE_TOO_MANY_REQUESTS_MAX_RETRIES="$CANDLE_TOO_MANY_MAX_RETRIES" \
    -e ANGEL_ONE_CANDLE_CACHE_TTL_SEC="330" \
    -e ANGEL_ONE_TOO_MANY_REQUESTS_MAX_RETRIES="$TOO_MANY_MAX_RETRIES" \
    -e ANGEL_ONE_TOO_MANY_REQUESTS_BACKOFF_BASE_SEC="$TOO_MANY_BACKOFF_BASE_SEC" \
    -e ANGEL_ONE_TOO_MANY_REQUESTS_BACKOFF_MAX_SEC="$TOO_MANY_BACKOFF_MAX_SEC" \
    -e AXON_MARKET_SCAN_BATCH_SIZE="$MARKET_SCAN_BATCH_SIZE" \
    -e AXON_DATABASE_URL="$DB_URL" \
    -e TZ="Asia/Kolkata" \
    -e PYTHONUNBUFFERED="1" \
    "$REGISTRY_URL/$IMAGE_NAME:latest" \
    streamlit run dashboard/app.py --server.port 8501 --server.address 0.0.0.0
'@
az vm run-command invoke `
    --resource-group $ResourceGroup `
    --name $VmName `
    --command-id RunShellScript `
    --scripts $remoteScript `
    --parameters $registryUrl $registryUser $registryPassword $ApiKey $ClientId $Pin $TotpSecret $ImageName $LtpMinIntervalSec $CandleMinIntervalSec $TooManyRequestsMaxRetries $CandleTooManyRequestsMaxRetries $TooManyRequestsBackoffBaseSec $TooManyRequestsBackoffMaxSec $MarketScanBatchSize | Out-Null

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
Write-Info "  sudo docker logs -f axon-scheduler"
Write-Info ""
Write-Info "To restart the container:"
Write-Info "  sudo docker restart axon-scheduler"
