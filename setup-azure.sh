#!/bin/bash

# Axon Aone - Complete Azure Setup Script
# Creates all necessary Azure resources and configurations

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Functions
print_header() {
    echo -e "\n${BLUE}========================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}========================================${NC}"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_info() {
    echo -e "${YELLOW}• $1${NC}"
}

# Check prerequisites
print_header "Checking Prerequisites"

if ! command -v az &> /dev/null; then
    print_error "Azure CLI is not installed"
    exit 1
fi

if ! command -v docker &> /dev/null; then
    print_error "Docker is not installed"
    exit 1
fi

print_success "Azure CLI and Docker are installed"

# Get configuration
print_header "Configuration"

read -p "Enter subscription ID (or press Enter for default): " SUBSCRIPTION_ID
read -p "Enter resource group name (default: axon-aone-rg): " RESOURCE_GROUP
RESOURCE_GROUP=${RESOURCE_GROUP:-"axon-aone-rg"}
read -p "Enter location (default: centralindia): " LOCATION
LOCATION=${LOCATION:-"centralindia"}
read -p "Enter container registry name (default: axonaoneacr): " REGISTRY_NAME
REGISTRY_NAME=${REGISTRY_NAME:-"axonaoneacr"}

print_info "Resource Group: $RESOURCE_GROUP"
print_info "Location: $LOCATION"
print_info "Registry: $REGISTRY_NAME"

# Login
print_header "Azure Authentication"

az login
if [ -n "$SUBSCRIPTION_ID" ]; then
    az account set --subscription "$SUBSCRIPTION_ID"
fi

CURRENT_SUBSCRIPTION=$(az account show --query id -o tsv)
print_success "Authenticated to subscription: $CURRENT_SUBSCRIPTION"

# Create resource group
print_header "Creating Resource Group"

if az group exists --name "$RESOURCE_GROUP" | grep -q true; then
    print_info "Resource group already exists"
else
    az group create --name "$RESOURCE_GROUP" --location "$LOCATION"
    print_success "Resource group created"
fi

# Create container registry
print_header "Creating Container Registry"

if az acr show --name "$REGISTRY_NAME" --resource-group "$RESOURCE_GROUP" 2>/dev/null; then
    print_info "Registry already exists"
else
    az acr create --name "$REGISTRY_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --sku Basic --admin-enabled true
    print_success "Container registry created"
fi

REGISTRY_URL="${REGISTRY_NAME}.azurecr.io"
REGISTRY_USER=$(az acr credential show --name "$REGISTRY_NAME" --query username -o tsv)
REGISTRY_PASSWORD=$(az acr credential show --name "$REGISTRY_NAME" --query "passwords[0].value" -o tsv)

print_success "Registry URL: $REGISTRY_URL"

# Enable admin user for ACR
az acr update --name "$REGISTRY_NAME" --admin-enabled true

# Create Key Vault
print_header "Creating Azure Key Vault"

KEYVAULT_NAME="${RESOURCE_GROUP}-kv"

if az keyvault show --name "$KEYVAULT_NAME" --resource-group "$RESOURCE_GROUP" 2>/dev/null; then
    print_info "Key Vault already exists"
else
    az keyvault create --name "$KEYVAULT_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --location "$LOCATION"
    print_success "Key Vault created: $KEYVAULT_NAME"
fi

# Prompt for credentials
print_header "Credentials Setup"

read -sp "Enter Angel One API Key: " API_KEY
echo
read -sp "Enter Angel One Client ID: " CLIENT_ID
echo
read -sp "Enter Angel One PIN: " PIN
echo
read -sp "Enter Angel One TOTP Secret (Base32): " TOTP_SECRET
echo

# Store credentials in Key Vault
print_info "Storing credentials in Key Vault..."
az keyvault secret set --vault-name "$KEYVAULT_NAME" \
    --name "angel-one-api-key" --value "$API_KEY"
az keyvault secret set --vault-name "$KEYVAULT_NAME" \
    --name "angel-one-client-id" --value "$CLIENT_ID"
az keyvault secret set --vault-name "$KEYVAULT_NAME" \
    --name "angel-one-pin" --value "$PIN"
az keyvault secret set --vault-name "$KEYVAULT_NAME" \
    --name "angel-one-totp-secret" --value "$TOTP_SECRET"

print_success "Credentials stored in Key Vault"

# Create Application Insights
print_header "Creating Application Insights"

APPINSIGHTS_NAME="${RESOURCE_GROUP}-insights"

if az monitor app-insights component show --name "$APPINSIGHTS_NAME" \
    --resource-group "$RESOURCE_GROUP" 2>/dev/null; then
    print_info "Application Insights already exists"
else
    az monitor app-insights component create \
        --app "$APPINSIGHTS_NAME" \
        --location "$LOCATION" \
        --resource-group "$RESOURCE_GROUP" \
        --application-type web
    print_success "Application Insights created"
fi

# Create Log Analytics Workspace
print_header "Creating Log Analytics Workspace"

LOG_ANALYTICS_NAME="${RESOURCE_GROUP}-logs"

if az monitor log-analytics workspace show --name "$LOG_ANALYTICS_NAME" \
    --resource-group "$RESOURCE_GROUP" 2>/dev/null; then
    print_info "Log Analytics workspace already exists"
else
    az monitor log-analytics workspace create \
        --name "$LOG_ANALYTICS_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --location "$LOCATION"
    print_success "Log Analytics workspace created"
fi

# Create Storage Account for logs and backups
print_header "Creating Storage Account"

STORAGE_ACCOUNT_NAME=$(echo "axontrade${RANDOM}" | tr -d ' ')

if az storage account show --name "$STORAGE_ACCOUNT_NAME" \
    --resource-group "$RESOURCE_GROUP" 2>/dev/null; then
    print_info "Storage account already exists"
else
    az storage account create \
        --name "$STORAGE_ACCOUNT_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --location "$LOCATION" \
        --sku Standard_LRS \
        --kind StorageV2 \
        --https-only true \
        --min-tls-version TLS1_2

    print_success "Storage Account created: $STORAGE_ACCOUNT_NAME"
    
    # Create containers
    STORAGE_KEY=$(az storage account keys list \
        --account-name "$STORAGE_ACCOUNT_NAME" \
        --query "[0].value" -o tsv)
    
    az storage container create \
        --account-name "$STORAGE_ACCOUNT_NAME" \
        --account-key "$STORAGE_KEY" \
        --name logs
    
    az storage container create \
        --account-name "$STORAGE_ACCOUNT_NAME" \
        --account-key "$STORAGE_KEY" \
        --name backups
    
    print_success "Storage containers created"
fi

# Generate configuration file
print_header "Generating Configuration Files"

cat > .env.azure <<EOF
# Generated Azure Configuration
# $(date)

AZURE_SUBSCRIPTION_ID=$CURRENT_SUBSCRIPTION
AZURE_RESOURCE_GROUP=$RESOURCE_GROUP
AZURE_LOCATION=$LOCATION

REGISTRY_NAME=$REGISTRY_NAME
REGISTRY_URL=$REGISTRY_URL
REGISTRY_USERNAME=$REGISTRY_USER
REGISTRY_PASSWORD=$REGISTRY_PASSWORD

KEYVAULT_NAME=$KEYVAULT_NAME
KEYVAULT_URI=https://${KEYVAULT_NAME}.vault.azure.net/

APPINSIGHTS_NAME=$APPINSIGHTS_NAME
LOG_ANALYTICS_NAME=$LOG_ANALYTICS_NAME
STORAGE_ACCOUNT_NAME=$STORAGE_ACCOUNT_NAME

ANGEL_ONE_API_KEY=\$(az keyvault secret show --vault-name $KEYVAULT_NAME --name angel-one-api-key --query value -o tsv)
ANGEL_ONE_CLIENT_ID=\$(az keyvault secret show --vault-name $KEYVAULT_NAME --name angel-one-client-id --query value -o tsv)
ANGEL_ONE_PIN=\$(az keyvault secret show --vault-name $KEYVAULT_NAME --name angel-one-pin --query value -o tsv)
ANGEL_ONE_TOTP_SECRET=\$(az keyvault secret show --vault-name $KEYVAULT_NAME --name angel-one-totp-secret --query value -o tsv)

MOCK_MODE=false
TZ=Asia/Kolkata
EOF

print_success "Configuration file created: .env.azure"

# Create deployment summary
cat > AZURE_DEPLOYMENT_SUMMARY.txt <<EOF
================================================================================
AXON AONE - AZURE DEPLOYMENT SUMMARY
Generated: $(date)
================================================================================

RESOURCES CREATED:
- Resource Group: $RESOURCE_GROUP
- Container Registry: $REGISTRY_NAME ($REGISTRY_URL)
- Key Vault: $KEYVAULT_NAME
- Application Insights: $APPINSIGHTS_NAME
- Log Analytics: $LOG_ANALYTICS_NAME
- Storage Account: $STORAGE_ACCOUNT_NAME

DEPLOYMENT COMMANDS:

1. Build and push Docker image:
   docker build -t $REGISTRY_URL/axon-aone:latest .
   az acr login --name $REGISTRY_NAME
   docker push $REGISTRY_URL/axon-aone:latest

2. Deploy to Container Instances:
   az container create \\
     --resource-group $RESOURCE_GROUP \\
     --name axon-aone-aci \\
     --image $REGISTRY_URL/axon-aone:latest \\
     --registry-username $REGISTRY_USER \\
     --registry-password $(echo $REGISTRY_PASSWORD | sed 's/./*/g') \\
     --environment-variables \\
       ANGEL_ONE_API_KEY=\$API_KEY \\
       ANGEL_ONE_CLIENT_ID=\$CLIENT_ID \
       ANGEL_ONE_PIN=\$PIN \
       ANGEL_ONE_TOTP_SECRET=\$TOTP_SECRET

3. View logs:
   az container logs --resource-group $RESOURCE_GROUP --name axon-aone-aci -f

4. Stop container:
   az container stop --resource-group $RESOURCE_GROUP --name axon-aone-aci

5. Delete resources:
   az group delete --name $RESOURCE_GROUP --yes

NEXT STEPS:
1. Deploy Docker image: docker build -t $REGISTRY_URL/axon-aone:latest .
2. Push to registry: docker push $REGISTRY_URL/axon-aone:latest
3. Run deployment script: ./deploy-azure.sh
4. Monitor in Azure Portal: https://portal.azure.com
5. Setup alerts and monitoring

KEYVAULT SECRETS:
- angel-one-api-key
- angel-one-client-id
- angel-one-pin
- angel-one-totp-secret

For additional commands, see AZURE_QUICKSTART.md

================================================================================
EOF

print_success "Deployment summary created: AZURE_DEPLOYMENT_SUMMARY.txt"

# Print summary
print_header "Setup Complete!"

echo -e "\n${GREEN}All Azure resources have been created successfully!${NC}\n"

echo -e "Next steps:"
echo -e "1. Build Docker image:"
echo -e "   ${YELLOW}docker build -t ${REGISTRY_URL}/axon-aone:latest .${NC}"
echo -e "\n2. Login to registry:"
echo -e "   ${YELLOW}az acr login --name ${REGISTRY_NAME}${NC}"
echo -e "\n3. Push image:"
echo -e "   ${YELLOW}docker push ${REGISTRY_URL}/axon-aone:latest${NC}"
echo -e "\n4. Deploy to Azure:"
echo -e "   ${YELLOW}./deploy-azure.sh${NC}"
echo -e "\n5. View configuration:"
echo -e "   ${YELLOW}cat .env.azure${NC}"
echo -e "\n6. Monitor deployment:"
echo -e "   ${YELLOW}az container logs --resource-group ${RESOURCE_GROUP} --name axon-aone-aci -f${NC}"

print_info "Configuration saved to: .env.azure"
print_info "Deployment summary saved to: AZURE_DEPLOYMENT_SUMMARY.txt"
echo ""
