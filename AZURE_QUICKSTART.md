# Azure Deployment Guide (Legacy)

Deploy Axon Aone to Microsoft Azure for production-grade reliability.

> **Note:** The current **Axon** capital engine repository no longer includes the Azure deployment scripts or ARM templates referenced in this guide. Treat this document as historical reference for the original infra-enabled project.

---

## Prerequisites

1. **Azure CLI** - [Install Azure CLI](https://docs.microsoft.com/cli/azure/install-azure-cli)
2. **Docker Desktop** - For building container images
3. **Angel One Credentials** - API Key, Client ID, PIN, TOTP Secret

---

## Quick Start: Azure VM (Default: Standard_D2s_v3)

Deploy to a production-ready Ubuntu VM in South India. By default, the deployment script uses `Standard_D2s_v3` for more headroom; you can override the size (for example to `Standard_B1s` for the lowest cost option) with the `-VmSize` parameter.

### Step 1: Set Environment Variables

```powershell
# Windows PowerShell
$env:ANGEL_ONE_API_KEY = "your_api_key"
$env:ANGEL_ONE_CLIENT_ID = "your_client_id"
$env:ANGEL_ONE_PIN = "your_pin"
$env:ANGEL_ONE_TOTP_SECRET = "your_totp_secret"
```

```bash
# Linux/Mac
export ANGEL_ONE_API_KEY="your_api_key"
export ANGEL_ONE_CLIENT_ID="your_client_id"
export ANGEL_ONE_PIN="your_pin"
export ANGEL_ONE_TOTP_SECRET="your_totp_secret"
```

### Step 2: Run Deployment Script

```powershell
.\deploy-azure-vm-b1s.ps1
```

### Step 3: Verify Deployment

```bash
# SSH into the VM
ssh azureuser@<public_ip>

# Check container status
sudo docker ps

# View logs
sudo docker logs -f axon-aone
```

---

## Deployment Options Comparison

| Option | Setup Time | Monthly Cost | Best For |
|--------|-----------|--------------|----------|
| **Azure VM B1s** | 15 min | ~$10 | Full control, SSH access |
| **Container Instances** | 5 min | ~$15 | Quick serverless deployment |
| **App Service Free** | 5 min | $0 | Testing/development |
| **AKS** | 30 min | $$$ | Enterprise, auto-scaling |

---

## Option 2: Azure Container Instances

### Deploy with Azure CLI

```bash
# Login to Azure
az login

# Create resource group
az group create --name axon-aone-rg --location southindia

# Create container instance
az container create \
  --resource-group axon-aone-rg \
  --name axon-aone-aci \
  --image your_acr.azurecr.io/axon-aone:latest \
  --cpu 1 --memory 2 \
  --restart-policy Always \
  --environment-variables \
    ANGEL_ONE_API_KEY=your_api_key \
    ANGEL_ONE_CLIENT_ID=your_client_id \
    ANGEL_ONE_PIN=your_pin \
    ANGEL_ONE_TOTP_SECRET=your_totp_secret

# View logs
az container logs --resource-group axon-aone-rg --name axon-aone-aci --follow
```

> 💡 **Helper scripts available**: instead of typing these commands manually, you can use the provided scripts which build, push, and create the ACI instance for you:
>
> - Windows PowerShell: `./deploy-azure.ps1`
> - Linux/macOS: `./deploy-azure.sh`

### Manage Container

```bash
# Check status
az container show --resource-group axon-aone-rg --name axon-aone-aci

# Restart
az container restart --resource-group axon-aone-rg --name axon-aone-aci

# Stop (stops billing)
az container stop --resource-group axon-aone-rg --name axon-aone-aci

# Delete
az container delete --resource-group axon-aone-rg --name axon-aone-aci --yes
```

---

## Option 3: Azure App Service

### Deploy to App Service

```bash
# Create App Service Plan (Free tier)
az appservice plan create \
  --name axon-plan \
  --resource-group axon-aone-rg \
  --sku F1 \
  --is-linux

# Create Web App
az webapp create \
  --name axon-aone-app \
  --plan axon-plan \
  --resource-group axon-aone-rg \
  --deployment-container-image-name your_acr.azurecr.io/axon-aone:latest

# Configure environment
az webapp config appsettings set \
  --name axon-aone-app \
  --resource-group axon-aone-rg \
  --settings \
    ANGEL_ONE_API_KEY=your_api_key \
    ANGEL_ONE_CLIENT_ID=your_client_id \
    ANGEL_ONE_PIN=your_pin \
    ANGEL_ONE_TOTP_SECRET=your_totp_secret
```

---

## Option 4: Azure Kubernetes Service (AKS)

For enterprise deployments with auto-scaling:

### Setup AKS Cluster

```bash
# Create AKS cluster
az aks create \
  --name axon-aks \
  --resource-group axon-aone-rg \
  --node-count 2 \
  --attach-acr your_acr

# Get credentials
az aks get-credentials --name axon-aks --resource-group axon-aone-rg
```

### Deploy to Kubernetes

```bash
# Create secrets (edit k8s/02-secrets.yml first)
kubectl apply -f k8s/02-secrets.yml

# Deploy all resources
kubectl apply -f k8s/

# Check status
kubectl get pods -n axon-aone
kubectl logs -f deployment/axon-aone -n axon-aone
```

See `k8s/README.md` for detailed Kubernetes instructions.

---

## Cleanup Resources

```bash
# Delete entire resource group (removes all resources)
az group delete --name axon-aone-rg --yes

# Or delete specific resources
az container delete --resource-group axon-aone-rg --name axon-aone-aci --yes
az vm delete --resource-group axon-aone-rg --name axon-aone-vm --yes
```

---

## Troubleshooting

### Container Not Starting
1. Check logs: `az container logs --resource-group axon-aone-rg --name axon-aone-aci`
2. Verify credentials are correct
3. Check TOTP secret is in base32 format

### Authentication Failed
1. Run `python test_angel_connection.py` locally first
2. Verify all 4 credentials: API Key, Client ID, PIN, TOTP Secret
3. Check TOTP secret format (base32 like `SH263ORE3L6GJF5RRTO3E4UGR3`)

### VM SSH Connection Issues
1. Check NSG rules allow SSH (port 22)
2. Verify public IP: `az vm show -d -g axon-aone-rg -n axon-aone-vm --query publicIps`
3. Use correct username: `azureuser`

See [AZURE_TROUBLESHOOTING.md](AZURE_TROUBLESHOOTING.md) for more help.
