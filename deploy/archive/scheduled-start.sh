#!/bin/bash

# scheduled-start.sh
# Starts trading container at market open (9:15 AM IST)
# Use with Azure Logic Apps scheduler (runs daily at 9:15 AM IST)

set -e

# Configuration
RESOURCE_GROUP="axon-aone-rg"
CONTAINER_NAME="axon-aone-scheduled"
REGISTRY="axonaoneacr"
IMAGE="${REGISTRY}.azurecr.io/axon-aone:latest"

# Environment (set these in Logic App or before running)
ANGEL_ONE_API_KEY=${ANGEL_ONE_API_KEY:-""}
ANGEL_ONE_CLIENT_ID=${ANGEL_ONE_CLIENT_ID:-""}
ANGEL_ONE_PIN=${ANGEL_ONE_PIN:-""}
ANGEL_ONE_TOTP_SECRET=${ANGEL_ONE_TOTP_SECRET:-""}

echo "==================================="
echo "Market Open - Starting Container"
echo "==================================="
echo "Time: $(date)"
echo "Container: $CONTAINER_NAME"
echo ""

# Get registry credentials
REGISTRY_USER=$(az acr credential show --name $REGISTRY --query username -o tsv)
REGISTRY_PASSWORD=$(az acr credential show --name $REGISTRY --query "passwords[0].value" -o tsv)

# Check if container already exists
if az container show --resource-group $RESOURCE_GROUP --name $CONTAINER_NAME 2>/dev/null; then
    echo "Container already running, skipping start"
    exit 0
fi

# Create container (only runs during market hours)
echo "Starting container with minimal resources..."
echo "  CPU: 0.5 cores"
echo "  Memory: 1 GB"
echo "  Estimated cost: \$0.25/day during market hours"
echo ""

az container create \
    --resource-group $RESOURCE_GROUP \
    --name $CONTAINER_NAME \
    --image $IMAGE \
    --registry-login-server ${REGISTRY}.azurecr.io \
    --registry-username $REGISTRY_USER \
    --registry-password $REGISTRY_PASSWORD \
    --cpu 0.5 \
    --memory 1 \
    --environment-variables \
        ANGEL_ONE_API_KEY="$ANGEL_ONE_API_KEY" \
        ANGEL_ONE_CLIENT_ID="$ANGEL_ONE_CLIENT_ID" \
        ANGEL_ONE_PIN="$ANGEL_ONE_PIN" \
        ANGEL_ONE_TOTP_SECRET="$ANGEL_ONE_TOTP_SECRET" \
        TZ="Asia/Kolkata" \
        MOCK_MODE="false" \
        PYTHONUNBUFFERED="1" \
    --restart-policy Never \
    --command-line "python run_trader.py --schedule"

echo ""
echo "✓ Container started at $(date)"
echo "✓ Trading will run until scheduled stop at market close"
echo ""
echo "Monitor logs:"
echo "  az container logs -g $RESOURCE_GROUP -n $CONTAINER_NAME -f"
