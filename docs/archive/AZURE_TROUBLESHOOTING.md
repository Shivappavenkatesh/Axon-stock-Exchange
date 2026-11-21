# Azure Deployment Troubleshooting Guide (Legacy)

## Common Issues and Solutions

### 1. Azure CLI Authentication Issues

**Problem**: `az login` fails or credentials not found

**Solutions**:
```bash
# Clear cached credentials
az logout

# Login with device code (more reliable)
az login --use-device-code

# Or use Service Principal
az login --service-principal -u APP_ID -p PASSWORD --tenant TENANT_ID

# Check current subscription
az account show
```

### 2. Container Registry Access Denied

**Problem**: `authentication failed` when pushing to ACR

**Solutions**:
```bash
# Build in ACR instead of locally
az acr build --registry myregistry --image myimage:latest .

# Get registry credentials
az acr credential show --name myregistry --query passwords[0].value -o tsv

# Manually login to registry
az acr login --name myregistry

# Check registry access
az acr check-health --name myregistry
```

### 3. Container Instance Not Starting

**Problem**: Container stuck in "Creating" or "Waiting" state

**Solutions**:
```bash
# Check detailed logs
az container show --name mycontainer --resource-group mygroup --query containers[0].instanceView

# View container logs (if running)
az container logs --name mycontainer --resource-group mygroup

# Delete and redeploy
az container delete --name mycontainer --resource-group mygroup --yes

# Increase timeout
az container create ... --no-wait
```

### 4. Out of Memory or CPU Issues

**Problem**: Container crashes with OOM or high CPU

**Solutions**:
- Increase resources in deployment:
  ```bash
  az container delete --name mycontainer --resource-group mygroup --yes
  az container create ... --memory 4 --cpu 2
  ```
- In Kubernetes:
  ```bash
  kubectl set resources deployment axon-aone \
    -c axon-aone --limits=cpu=2000m,memory=4Gi
  ```

### 5. Application Crashes with ImportError

**Problem**: Module not found errors in container logs

**Solutions**:
```bash
# Ensure PYTHONPATH is set
az container create ... -e PYTHONPATH=src

# Verify requirements.txt
pip install -r requirements.txt

# Check if dependencies are in Dockerfile
docker build -t test .
docker run test python -c "import axon_aone"
```

### 6. Angel One Credentials Not Working

**Problem**: Trading fails with auth errors

**Solutions**:
```bash
# Verify credentials are set
az container show --name mycontainer --resource-group mygroup \
  --query "containers[0].environmentVariables" -o table

# Use Azure Key Vault instead
az keyvault secret set --vault-name mykv --name angel-one-api-key --value "key"

# Update container to use Key Vault
az container create ... \
  -e ANGEL_ONE_API_KEY="@/mnt/secrets/api-key"
```

### 7. Network/Connectivity Issues

**Problem**: Container able to run but can't connect to APIs

**Solutions**:
```bash
# Check if outbound traffic is blocked
az container exec --name mycontainer --resource-group mygroup \
  --exec-command "curl https://api.angelbroking.com"

# Increase timeout for API calls
# Edit config with longer timeouts

# Check firewall/NSG rules
az network nsg rule list --resource-group mygroup --nsg-name mynsg -o table
```

### 7a. PostgreSQL Hostname Resolution Fails on Azure VM

**Problem**: Application logs show `could not translate host name "axon-postgres" to address`

**Cause**: The app containers are not attached to the same user-defined Docker network as PostgreSQL, so Docker DNS cannot resolve the database container name.

**Solutions**:
```bash
# Check that the shared network exists
sudo docker network ls

# Inspect containers on the shared network
sudo docker network inspect axon-network

# If the network or containers are missing, rerun the deployment script
./deploy-azure-vm-b1s.ps1

# Verify PostgreSQL is healthy inside the database container
sudo docker exec axon-postgres pg_isready -U axon -d axon
```

### 8. High Azure Costs

**Problem**: Unexpected billing charges

**Solutions**:
```bash
# Use spot instances (cheaper but can be evicted)
# Set budget alerts in Azure Portal

# Schedule containers to run only during market hours
az container create ... --restart-policy OnFailure

# Delete unused resources
az group delete --name mygroup --yes

# Monitor with Cost Management
az costmanagement query --definition '{...}' -o table
```

### 9. GitHub Actions Deployment Fails

**Problem**: Workflow fails with Azure credentials error

**Solutions**:
```bash
# Create service principal for GitHub
az ad sp create-for-rbac --name "github-axon-aone" \
  --role contributor \
  --scopes /subscriptions/{subscriptionId} \
  --json-auth

# Add output to GitHub Secrets as AZURE_CREDENTIALS

# Verify workflow permissions
github.com/YOUR_REPO/settings/secrets/actions
```

### 10. Logs Not Persisting

**Problem**: Logs disappear after container restarts

**Solutions**:
```bash
# Use Azure File Share for persistent logs
az storage account create --name mysa --resource-group mygroup
az storage share create --account-name mysa --name logs

# Mount in container
az container create ... --volumes FileShare logs ...

# Or use Azure Blob Storage
az storage container create --account-name mysa --name logs
```

### 11. Kubernetes Pod Not Running

**Problem**: kubectl show pod in CrashLoopBackOff or Pending

**Solutions**:
```bash
# Check pod status
kubectl describe pod axon-aone -n axon-aone

# View logs
kubectl logs axon-aone -n axon-aone -f

# Check events
kubectl get events -n axon-aone

# Check resource availability
kubectl top nodes
kubectl top pod -n axon-aone

# Debug with shell
kubectl run -it --rm debug --image=ubuntu --restart=Never -- /bin/bash
```

### 12. Image Pull Errors in AKS

**Problem**: Pod can't pull image from registry

**Solutions**:
```bash
# Update image pull secret
kubectl create secret docker-registry azure-registry-credentials \
  --docker-server=myregistry.azurecr.io \
  --docker-username=myuser \
  --docker-password=mypassword \
  -n axon-aone

# Or use AKS integration
az aks update -n myakscluster -g mygroup \
  --attach-acr myregistry

# Verify attachment
az aks check-acr --name myakscluster \
  --resource-group mygroup \
  --acr myregistry.azurecr.io
```

## Monitoring & Debugging

### Enable Detailed Logging

```bash
# Set debug logging level
export PYTHONUNBUFFERED=1
export PYTHONASYNCDEBUG=1

# In container
az container create ... -e PYTHONUNBUFFERED=1
```

### Check Resource Usage

```bash
# Container Instances
az container list --resource-group mygroup \
  --query "[].{Name:name, CPU:containers[0].resources.requests.cpu, Memory:containers[0].resources.requests.memoryInGb}" \
  -o table

# AKS
kubectl top nodes
kubectl top pod -n axon-aone
```

### Stream Real-Time Logs

```bash
# Container Instances
az container logs --name mycontainer --resource-group mygroup --follow

# Kubernetes
kubectl logs deployment/axon-aone -n axon-aone -f
```

### Performance Metrics

```bash
# Set up Application Insights
az monitor app-insights component create \
  --app myapp --resource-group mygroup

# Query metrics
az monitor metrics list --resource /subscriptions/{sub}/resourceGroups/{group}/providers/microsoft.insights/components/{app}
```

## Quick Reference Commands

```bash
# Status checks
az container show --name mycontainer --resource-group mygroup
az container list --resource-group mygroup -o table
az acr repository list --name myregistry -o table

# Cleanup
az container delete --name mycontainer --resource-group mygroup --yes
az group delete --name mygroup --yes

# Logs
az container logs --name mycontainer --resource-group mygroup --tail 50
kubectl logs -f deployment/axon-aone -n axon-aone

# Restart
az container restart --name mycontainer --resource-group mygroup
kubectl rollout restart deployment/axon-aone -n axon-aone
```

## Getting Help

1. Check Azure service health: https://status.azure.com/
2. Azure documentation: https://docs.microsoft.com/azure/
3. AKS best practices: https://docs.microsoft.com/azure/aks/best-practices
4. Kubernetes docs: https://kubernetes.io/docs/
