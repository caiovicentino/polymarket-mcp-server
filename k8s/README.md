# Kubernetes Deployment

Deploy Polymarket MCP Server to Kubernetes for production-grade scalability and reliability.

## Prerequisites

- Kubernetes cluster (1.20+)
- `kubectl` configured
- Access to container registry (Docker Hub, GCR, etc.)

## Quick Start

### 1. Build and Push Image

```bash
# Build multi-arch image
docker buildx build --platform linux/amd64,linux/arm64 \
  -t your-registry/polymarket-mcp:latest \
  --push .

# Or tag and push existing image
docker tag polymarket-mcp:latest your-registry/polymarket-mcp:latest
docker push your-registry/polymarket-mcp:latest
```

### 2. Namespace

The bundled manifests declare `namespace: default`, so they deploy into the
`default` namespace as-is. Use a separate namespace only if you customize the
`namespace:` fields in the manifests yourself.

### 3. Create Secrets

```bash
# From literal values
kubectl create secret generic polymarket-mcp-secrets \
  --from-literal=POLYGON_PRIVATE_KEY=0x1234... \
  --from-literal=POLYGON_ADDRESS=0xABCD... \
  --from-literal=POLYMARKET_API_KEY=... \
  --from-literal=POLYMARKET_API_SECRET=... \
  --from-literal=POLYMARKET_PASSPHRASE=... \
  -n default
# Note: API_SECRET and PASSPHRASE are DIFFERENT values — do not reuse one for
# both, or request signing will fail.

# Or from .env file
kubectl create secret generic polymarket-mcp-secrets \
  --from-env-file=../.env \
  -n default
```

### 4. Deploy

```bash
# Apply all manifests
kubectl apply -f k8s/ -n default

# Or apply individually
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
```

### 5. Verify Deployment

```bash
# Check pods
kubectl get pods -n default

# Check logs
kubectl logs -f deployment/polymarket-mcp -n default

# Check status
kubectl describe deployment polymarket-mcp -n default
```

## Configuration

### ConfigMap

Edit `configmap.yaml` for non-sensitive configuration:

```yaml
data:
  LOG_LEVEL: "INFO"
  MAX_ORDER_SIZE_USD: "1000"
  # ... other settings
```

Apply changes:
```bash
kubectl apply -f k8s/configmap.yaml
kubectl rollout restart deployment/polymarket-mcp
```

### Secrets

Update secrets:
```bash
# Edit existing secret
kubectl edit secret polymarket-mcp-secrets

# Or recreate
kubectl delete secret polymarket-mcp-secrets
kubectl create secret generic polymarket-mcp-secrets --from-literal=...
```

### Resource Limits

Edit `deployment.yaml` to adjust resources:

```yaml
resources:
  requests:
    memory: "256Mi"
    cpu: "250m"
  limits:
    memory: "1Gi"
    cpu: "2000m"
```

## Scaling

### Horizontal Pod Autoscaling

Create HPA:

```bash
kubectl autoscale deployment polymarket-mcp \
  --cpu-percent=70 \
  --min=1 \
  --max=10 \
  -n default
```

Or use manifest:

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: polymarket-mcp
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: polymarket-mcp
  minReplicas: 1
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
```

### Manual Scaling

```bash
kubectl scale deployment polymarket-mcp --replicas=3
```

## Monitoring

### Logs

```bash
# Follow logs
kubectl logs -f deployment/polymarket-mcp

# Last 100 lines
kubectl logs deployment/polymarket-mcp --tail=100

# Previous container logs
kubectl logs deployment/polymarket-mcp --previous
```

### Events

```bash
# Watch events
kubectl get events --watch

# Deployment events
kubectl describe deployment polymarket-mcp
```

### Metrics

```bash
# Pod metrics (requires metrics-server)
kubectl top pod -l app=polymarket-mcp

# Node metrics
kubectl top nodes
```

## Troubleshooting

### Pod Not Starting

```bash
# Check pod status
kubectl describe pod -l app=polymarket-mcp

# Check events
kubectl get events --sort-by=.metadata.creationTimestamp

# Check logs
kubectl logs -l app=polymarket-mcp --all-containers
```

### ImagePullBackOff

```bash
# Check image
kubectl describe pod -l app=polymarket-mcp | grep -A 5 "Image:"

# Verify registry access
kubectl get secrets
```

### CrashLoopBackOff

```bash
# Check logs
kubectl logs -l app=polymarket-mcp --previous

# Check liveness probe
kubectl describe pod -l app=polymarket-mcp | grep -A 10 "Liveness:"
```

### Config Issues

```bash
# Verify ConfigMap
kubectl get configmap polymarket-mcp-config -o yaml

# Verify Secret
kubectl get secret polymarket-mcp-secrets -o yaml
```

## Updates

### Rolling Update

```bash
# Update image
kubectl set image deployment/polymarket-mcp \
  polymarket-mcp=your-registry/polymarket-mcp:v0.2.0

# Or edit deployment
kubectl edit deployment polymarket-mcp

# Watch rollout
kubectl rollout status deployment/polymarket-mcp
```

### Rollback

```bash
# Rollback to previous version
kubectl rollout undo deployment/polymarket-mcp

# Rollback to specific revision
kubectl rollout undo deployment/polymarket-mcp --to-revision=2

# Check rollout history
kubectl rollout history deployment/polymarket-mcp
```

## Backup and Restore

### Backup PVCs

```bash
# Create snapshot (if supported)
kubectl apply -f - <<EOF
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshot
metadata:
  name: polymarket-mcp-backup
spec:
  volumeSnapshotClassName: default
  source:
    persistentVolumeClaimName: polymarket-mcp-data
EOF
```

### Export Resources

```bash
# Export all resources
kubectl get deployment,configmap,secret,pvc,service \
  -l app=polymarket-mcp \
  -o yaml > backup.yaml
```

## Cleanup

### Delete Resources

```bash
# Delete deployment
kubectl delete -f k8s/

# Delete namespace (if used)
kubectl delete namespace polymarket

# Delete PVCs (optional - will delete data!)
kubectl delete pvc polymarket-mcp-logs polymarket-mcp-data
```

## Production Best Practices

1. **Use Namespaces**: Isolate resources
2. **Resource Limits**: Always set requests and limits
3. **Health Checks**: Configure liveness and readiness probes
4. **Security**: Use RBAC, PodSecurityPolicies, NetworkPolicies
5. **Monitoring**: Integrate with Prometheus/Grafana
6. **Logging**: Use centralized logging (ELK, Loki)
7. **Secrets**: Use external secret managers (Vault, AWS Secrets Manager)
8. **Backups**: Regular PVC backups
9. **Updates**: Use rolling updates with health checks
10. **Testing**: Test in staging before production

## Advanced Configuration

### Network Policies

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: polymarket-mcp
spec:
  podSelector:
    matchLabels:
      app: polymarket-mcp
  policyTypes:
  - Ingress
  - Egress
  egress:
  - to:
    - namespaceSelector: {}
    ports:
    - protocol: TCP
      port: 443  # HTTPS
```

### Service Mesh

For Istio integration:

```yaml
apiVersion: networking.istio.io/v1beta1
kind: VirtualService
metadata:
  name: polymarket-mcp
spec:
  hosts:
  - polymarket-mcp
  http:
  - route:
    - destination:
        host: polymarket-mcp
        subset: v1
```

## Getting Help

- Kubernetes Docs: https://kubernetes.io/docs/
- kubectl Cheat Sheet: https://kubernetes.io/docs/reference/kubectl/cheatsheet/
- Troubleshooting: https://kubernetes.io/docs/tasks/debug/

---

**Ready for production?** Deploy Polymarket MCP Server to Kubernetes!
