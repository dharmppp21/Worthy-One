# SignForge Helm Chart

A production-ready Helm chart for deploying SignalForge on Kubernetes with auto-discovery enabled.

## Prerequisites

- Kubernetes 1.20+
- Helm 3.0+
- (Optional) Helm unittest plugin for running tests

## Install

### Basic install (with embedded PostgreSQL and Redis)

```bash
helm install signforge ./helm/signforge \
  --namespace monitoring \
  --create-namespace
```

### With external PostgreSQL

```bash
helm install signforge ./helm/signforge \
  --namespace monitoring \
  --create-namespace \
  --set postgresql.enabled=false \
  --set env.DATABASE_URL=postgresql://user:pass@my-postgres:5432/signforge
```

### With limited RBAC (single namespace discovery)

```bash
helm install signforge ./helm/signforge \
  --namespace monitoring \
  --create-namespace \
  --set discovery.kubernetes.clusterRole=false
```

### Enabling Kafka

```bash
helm install signforge ./helm/signforge \
  --namespace monitoring \
  --create-namespace \
  --set kafka.enabled=true
```

### With custom values file

```bash
helm install signforge ./helm/signforge \
  --namespace monitoring \
  --create-namespace \
  -f my-values.yaml
```

## Upgrade

```bash
helm upgrade signforge ./helm/signforge \
  --namespace monitoring
```

## Uninstall

```bash
helm uninstall signforge --namespace monitoring
```

## Configuration

### Key values

| Parameter | Description | Default |
|-----------|-------------|---------|
| `replicaCount` | Number of backend replicas | `1` |
| `image.repository` | Image repository | `ghcr.io/dharmppp21/signforge` |
| `image.tag` | Image tag | `latest` |
| `image.pullPolicy` | Image pull policy | `IfNotPresent` |
| `service.type` | Service type | `ClusterIP` |
| `service.port` | Service port | `8000` |
| `postgresql.enabled` | Enable PostgreSQL subchart | `true` |
| `redis.enabled` | Enable Redis subchart | `true` |
| `kafka.enabled` | Enable Kafka subchart | `false` |
| `discovery.enabled` | Enable service discovery | `true` |
| `discovery.interval` | Discovery interval in seconds | `30` |
| `discovery.providers` | Active discovery providers | `["kubernetes", "docker", "process", "config"]` |
| `discovery.kubernetes.clusterRole` | Use ClusterRole for cross-namespace discovery | `true` |
| `rbac.create` | Create RBAC resources | `true` |
| `serviceAccount.create` | Create ServiceAccount | `true` |
| `ingress.enabled` | Enable Ingress | `false` |
| `hpa.enabled` | Enable HorizontalPodAutoscaler | `false` |

### Full values reference

See `values.yaml` for all available configuration options.

## Discovery

By default, SignForge discovers services in the Kubernetes cluster. The RBAC configuration grants the minimal permissions needed for service discovery:

- Pods, Services, Endpoints, Nodes, Namespaces: `get`, `list`, `watch`
- Deployments, ReplicaSets, StatefulSets, DaemonSets: `get`, `list`, `watch`
- EndpointSlices: `get`, `list`, `watch`

To restrict discovery to a single namespace, set `discovery.kubernetes.clusterRole=false`.

## Testing

Run the chart test script:

```bash
./helm/test-chart.sh
```

Run Helm tests after installation:

```bash
helm test signforge --namespace monitoring
```

## License

MIT
