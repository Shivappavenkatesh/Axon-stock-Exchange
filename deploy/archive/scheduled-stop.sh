#!/bin/bash

# scheduled-stop.sh
# Stops trading container at market close (3:30 PM IST)
# Use with Azure Logic Apps scheduler (runs daily at 3:30 PM IST)

set -e

# Configuration
RESOURCE_GROUP="axon-aone-rg"
CONTAINER_NAME="axon-aone-scheduled"

echo "==================================="
echo "Market Close - Stopping Container"
echo "==================================="
echo "Time: $(date)"
echo "Container: $CONTAINER_NAME"
echo ""

# Check if container exists
if ! az container show --resource-group $RESOURCE_GROUP --name $CONTAINER_NAME 2>/dev/null; then
    echo "Container not running, nothing to stop"
    exit 0
fi

# Stop and delete container
echo "Stopping container..."
az container delete \
    --resource-group $RESOURCE_GROUP \
    --name $CONTAINER_NAME \
    --yes

echo ""
echo "✓ Container stopped at $(date)"
echo "✓ Trading resumed tomorrow at market open"
echo ""
echo "Cost saved by stopping container at market close:"
echo "  ~80% savings compared to 24/7 operation"
echo "  Estimated: \$3-5/month instead of \$200/month"
