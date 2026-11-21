# Kubernetes Deployment Files (AKS)

This directory contains separate, properly-formatted YAML files for deploying Axon Aone to Azure Kubernetes Service (AKS).

## Files

- `01-namespace.yml` - Kubernetes namespace
- `02-secrets.yml` - Angel One credentials (encrypted secrets)
- `03-configmap.yml` - Application configuration
- `04-serviceaccount-rbac.yml` - Service account and role-based access control
- `05-deployment.yml` - Main application deployment
- `06-service.yml` - Kubernetes service for network exposure
- `07-hpa.yml` - Horizontal Pod Autoscaler for auto-scaling
- `08-pdb.yml` - Pod Disruption Budget for high availability

## Prerequisites

1. Azure Kubernetes Service cluster created
2. `kubectl` configured to access your AKS cluster
3. Container image pushed to Azure Container Registry

## Setup Instructions

### 1. Create AKS Cluster (if not already done)

```bash
az aks create \
  --name axon-aone-aks \
  --resource-group axon-aone-rg \
  --node-count 2 \
  --vm-set-type VirtualMachineScaleSets \
  --attach-acr axonaoneacr

az aks get-credentials \
  --name axon-aone-aks \
  --resource-group axon-aone-rg
```

### 2. Update Secrets with Your Credentials

Edit `02-secrets.yml` and replace placeholder values:

```bash
# Method 1: Edit file directly
notepad 02-secrets.yml  # Windows
# or
nano 02-secrets.yml     # Linux/macOS

# Update these values:
# api-key: "YOUR_ACTUAL_API_KEY"
# access-token: "YOUR_ACTUAL_TOKEN"
```

### 3. Create Image Pull Secret (for ACR)

If not using AKS-integrated ACR access:

```bash
kubectl create secret docker-registry azure-registry-credentials \
  --docker-server=axonaoneacr.azurecr.io \
  --docker-username=axonaoneacr \
  --docker-password=YOUR_REGISTRY_PASSWORD \
  --docker-email=admin@axon.local \
  -n axon-aone

# Add to 05-deployment.yml if needed:
# imagePullSecrets:
#   - name: azure-registry-credentials
```

### 4. Deploy All Files

Deploy in order:

```bash
# Option 1: Deploy all files (recommended)
kubectl apply -f .

# Option 2: Deploy specific files in order
kubectl apply -f 01-namespace.yml
kubectl apply -f 02-secrets.yml
kubectl apply -f 03-configmap.yml
kubectl apply -f 04-serviceaccount-rbac.yml
kubectl apply -f 05-deployment.yml
kubectl apply -f 06-service.yml
kubectl apply -f 07-hpa.yml
kubectl apply -f 08-pdb.yml
```

### 5. Verify Deployment

```bash
# Check namespace
kubectl get namespace axon-aone

# Check secrets
kubectl get secrets -n axon-aone

# Check configuration
kubectl get configmaps -n axon-aone

# Check deployment
kubectl get deployment axon-aone -n axon-aone

# Check pods
kubectl get pods -n axon-aone

# Check service
kubectl get service axon-aone-service -n axon-aone

# Check HPA status
kubectl get hpa axon-aone-hpa -n axon-aone
```

### 6. View Logs

```bash
# View pod logs
kubectl logs -f deployment/axon-aone -n axon-aone

# View logs from specific pod
kubectl logs -f axon-aone-<pod-id> -n axon-aone

# Stream logs from all pods
kubectl logs -f deployment/axon-aone -n axon-aone --all-containers
```

### 7. Debugging

```bash
# Describe pod for detailed information
kubectl describe pod axon-aone-<pod-id> -n axon-aone

# Get detailed deployment info
kubectl describe deployment axon-aone -n axon-aone

# Check resource usage
kubectl top nodes
kubectl top pod -n axon-aone

# Get all events in namespace
kubectl get events -n axon-aone
```

## Updating Credentials

If you need to update Angel One credentials:

```bash
# Option 1: Delete and recreate secret
kubectl delete secret angel-one-credentials -n axon-aone
kubectl apply -f 02-secrets.yml

# Option 2: Edit secret directly
kubectl edit secret angel-one-credentials -n axon-aone

# Restart pods to pick up new credentials
kubectl rollout restart deployment/axon-aone -n axon-aone
```

## Scaling

```bash
# Manual scaling
kubectl scale deployment axon-aone --replicas=3 -n axon-aone

# Check HPA status
kubectl get hpa axon-aone-hpa -n axon-aone -w

# HPA will automatically scale based on CPU (70%) and memory (80%) utilization
```

## Troubleshooting

### Pod not starting
```bash
kubectl describe pod axon-aone-<id> -n axon-aone
kubectl logs axon-aone-<id> -n axon-aone
```

### Image pull errors
```bash
# Verify image exists in ACR
az acr repository list --name axonaoneacr

# Verify image pull secret
kubectl get secrets -n axon-aone
```

### Secret not found
```bash
# Verify secrets exist
kubectl get secrets -n axon-aone
kubectl get secret angel-one-credentials -n axon-aone -o yaml
```

### Connection issues
```bash
# Test connectivity from pod
kubectl run -it --rm debug --image=ubuntu --restart=Never -- /bin/bash

# Inside pod:
curl https://api.angelbroking.com
```

## Cleanup

Remove all resources:

```bash
# Delete namespace (cascades to all resources)
kubectl delete namespace axon-aone

# Or delete specific resources
kubectl delete -f .
```

## Best Practices

1. ✅ Use separate YAML files per resource
2. ✅ Define resource requests and limits
3. ✅ Use health checks (liveness and readiness probes)
4. ✅ Store secrets in Key Vault, reference them
5. ✅ Use namespaces for isolation
6. ✅ Enable RBAC for security
7. ✅ Monitor with Log Analytics and Application Insights
8. ✅ Use StatefulSets for stateful workloads
9. ✅ Implement pod disruption budgets for reliability
10. ✅ Use horizontal pod autoscaling for elasticity

## CI/CD Integration

To automate deployments with GitHub Actions:

```yaml
# In .github/workflows/kubernetes-deploy.yml
- name: Deploy to AKS
  run: |
    az aks get-credentials --name axon-aone-aks --resource-group axon-aone-rg
    kubectl apply -f k8s/
```

## More Information

- [Kubernetes Documentation](https://kubernetes.io/docs/)
- [AKS Best Practices](https://docs.microsoft.com/azure/aks/best-practices)
- [kubectl Cheat Sheet](https://kubernetes.io/docs/reference/kubectl/cheatsheet/)
