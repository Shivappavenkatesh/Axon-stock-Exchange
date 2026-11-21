#!/bin/bash

# Axon Aone - Azure Container Instances Deployment Script (Bash)
# Deploys the trading scheduler to Azure Container Instances

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Configuration
RESOURCE_GROUP=${RESOURCE_GROUP:-"axon-aone-rg"}
LOCATION=${LOCATION:-"southindia"}
REGISTRY_NAME=${REGISTRY_NAME:-"axonaoneacr"}
CONTAINER_GROUP=${CONTAINER_GROUP:-"axon-aone-aci"}
IMAGE_NAME=${IMAGE_NAME:-"axon-aone"}
SUBSCRIPTION_ID=${SUBSCRIPTION_ID:-""}

# Angel One Credentials
API_KEY=${ANGEL_ONE_API_KEY:-""}
CLIENT_ID=${ANGEL_ONE_CLIENT_ID:-""}
PIN=${ANGEL_ONE_PIN:-""}
TOTP_SECRET=${ANGEL_ONE_TOTP_SECRET:-""}
MOCK_MODE=${MOCK_MODE:-"false"}

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Axon Aone - Azure ACI Deployment${NC}"
echo -e "${GREEN}========================================${NC}"

# Check prerequisites
echo -e "\n${YELLOW}Checking prerequisites...${NC}"

if ! command -v az &> /dev/null; then
    echo -e "${RED}Azure CLI is not installed. Install: https://docs.microsoft.com/cli/azure/${NC}"
    exit 1
fi

if ! command -v docker &> /dev/null; then
    echo -e "${RED}Docker is not installed.${NC}"
    exit 1
fi

echo -e "${GREEN}OK - Prerequisites check passed${NC}"

# Login to Azure
echo -e "\n${YELLOW}Logging in to Azure...${NC}"
az login

if [ -n "$SUBSCRIPTION_ID" ]; then
    az account set --subscription "$SUBSCRIPTION_ID"
fi

# Create resource group
echo -e "\n${YELLOW}Creating resource group: $RESOURCE_GROUP${NC}"
az group create --name "$RESOURCE_GROUP" --location "$LOCATION"
echo -e "${GREEN}OK - Resource group created${NC}"

# Create container registry
echo -e "\n${YELLOW}Creating container registry: $REGISTRY_NAME${NC}"
az acr create --resource-group "$RESOURCE_GROUP" --name "$REGISTRY_NAME" --sku Basic
echo -e "${GREEN}OK - Container registry created${NC}"

# Build and push Docker image
echo -e "\n${YELLOW}Building and pushing Docker image...${NC}"
az acr build --registry "$REGISTRY_NAME" \
    --image "${IMAGE_NAME}:latest" \
    --image "${IMAGE_NAME}:$(date +%Y%m%d_%H%M%S)" .
echo -e "${GREEN}OK - Docker image built and pushed${NC}"

# Get registry credentials
echo -e "\n${YELLOW}Getting registry credentials...${NC}"
REGISTRY_USER=$(az acr credential show --name "$REGISTRY_NAME" --query username -o tsv)
REGISTRY_PASSWORD=$(az acr credential show --name "$REGISTRY_NAME" --query "passwords[0].value" -o tsv)
REGISTRY_URL="${REGISTRY_NAME}.azurecr.io"

# Validate credentials
echo -e "\n${YELLOW}Checking Angel One credentials...${NC}"
if [ -z "$API_KEY" ]; then
    read -p "Enter Angel One API Key: " API_KEY
fi
if [ -z "$CLIENT_ID" ]; then
    read -p "Enter Angel One Client ID: " CLIENT_ID
fi
if [ -z "$PIN" ]; then
    read -p "Enter Angel One PIN: " PIN
fi
if [ -z "$TOTP_SECRET" ]; then
    read -p "Enter Angel One TOTP Secret: " TOTP_SECRET
fi

if [ -z "$API_KEY" ] || [ -z "$CLIENT_ID" ] || [ -z "$PIN" ] || [ -z "$TOTP_SECRET" ]; then
    echo -e "${RED}All credentials required (API Key, Client ID, PIN, TOTP Secret)${NC}"
    exit 1
fi
echo -e "${GREEN}OK - Credentials captured${NC}"

# Create container instance
echo -e "\n${YELLOW}Creating container instance: $CONTAINER_GROUP${NC}"
az container create \
    --resource-group "$RESOURCE_GROUP" \
    --name "$CONTAINER_GROUP" \
    --image "${REGISTRY_URL}/${IMAGE_NAME}:latest" \
    --registry-login-server "$REGISTRY_URL" \
    --registry-username "$REGISTRY_USER" \
    --registry-password "$REGISTRY_PASSWORD" \
    --environment-variables \
        ANGEL_ONE_API_KEY="$API_KEY" \
        ANGEL_ONE_CLIENT_ID="$CLIENT_ID" \
        ANGEL_ONE_PIN="$PIN" \
        ANGEL_ONE_TOTP_SECRET="$TOTP_SECRET" \
        MOCK_MODE="$MOCK_MODE" \
        TZ="Asia/Kolkata" \
        PYTHONUNBUFFERED="1" \
    --memory 2 \
    --cpu 1 \
    --restart-policy Always \
    --command-line "python run_trader.py --schedule" \
    --ports 8080

echo -e "${GREEN}OK - Container instance created${NC}"

# Wait for container
echo -e "\n${YELLOW}Waiting for container...${NC}"
sleep 10

# Check status
echo -e "\n${YELLOW}Container Status:${NC}"
az container show --resource-group "$RESOURCE_GROUP" --name "$CONTAINER_GROUP" \
    --query "{ Name: name, State: containers[0].instanceView.currentState.state }" -o table

echo -e "\n${YELLOW}Recent Logs:${NC}"
az container logs --resource-group "$RESOURCE_GROUP" --name "$CONTAINER_GROUP" --tail 20

echo -e "\n${GREEN}========================================${NC}"
echo -e "${GREEN}Deployment Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo "Resource Group: $RESOURCE_GROUP"
echo "Container: $CONTAINER_GROUP"
echo ""
echo "View logs:"
echo "  az container logs --resource-group $RESOURCE_GROUP --name $CONTAINER_GROUP -f"
echo ""
echo "Restart:"
echo "  az container restart --resource-group $RESOURCE_GROUP --name $CONTAINER_GROUP"
echo ""
echo "Delete:"
echo "  az group delete --name $RESOURCE_GROUP --yes"
