# Architecture Guide — Credit Card Fraud Detection Platform

> **DEMO SYSTEM** — designed to teach DevOps/MLOps architecture. Not for real financial use.

---

## 1. System Overview

```
                    ┌───────────────────────────────┐
                    │       Client / Payment App     │
                    └──────────────┬────────────────┘
                                   │ POST /predict
                                   ▼
                    ┌──────────────────────────────────┐
                    │  NGINX Ingress Controller         │
                    │  (API Gateway + Load Balancer)    │
                    │  • Rate limiting                  │
                    │  • Path routing                   │
                    │  • Health-based routing           │
                    └──────────────┬───────────────────┘
                                   │
                    ┌──────────────▼───────────────────┐
                    │  Kubernetes Service (ClusterIP)   │
                    └──────────────┬───────────────────┘
                                   │  Round-robin
                     ┌─────────────┼─────────────┐
                     ▼             ▼             ▼
               ┌──────────┐ ┌──────────┐ ┌──────────┐
               │FastAPI   │ │FastAPI   │ │FastAPI   │   HPA
               │Pod 1     │ │Pod 2     │ │Pod N...  │ ◄─────
               │          │ │          │ │          │  2-10
               │ XGBoost  │ │ XGBoost  │ │ XGBoost  │  replicas
               │ model    │ │ model    │ │ model    │
               └────┬─────┘ └────┬─────┘ └────┬─────┘
                    │             │             │
                    └──────┬──────┘─────────────┘
                           │ asyncio.create_task()
                           ▼
               ┌───────────────────────────────┐
               │  Kafka — fraud-transactions   │
               └───────────────┬───────────────┘
                               ▼
               ┌───────────────────────────────┐
               │  Kafka Consumer Service        │
               │  (analytics / storage)         │
               └───────────────────────────────┘

FastAPI pods also expose:
               ┌───────────────────────────────┐
               │  /metrics                      │
               └───────────────┬───────────────┘
                               ▼
               ┌───────────────────────────────┐
               │  Prometheus                   │
               └───────────────┬───────────────┘
                               ▼
               ┌───────────────────────────────┐
               │  Grafana                      │
               └───────────────────────────────┘
```

---

## 2. ML Pipeline

### Model: XGBoost (Gradient Boosted Decision Trees)

```
Raw Transaction (JSON)
        │
        ▼
Pydantic Validation         ← rejects malformed requests with 422
        │
        ▼
Feature Engineering         ← app/features.py (shared by training & inference)
  • log(amount)
  • category label-encoded
  • state label-encoded
  • transaction_hour
  • log(distance)
  • device_type encoded
  • is_night  (hour < 6 or > 22)
  • is_high_amount (amount > 500)
        │
        ▼
XGBoost .predict_proba()    ← returns [p_legit, p_fraud]
        │
        ▼
Decision Engine             ← app/decision.py (configurable via env vars)
  < 0.60  → APPROVE
  0.60-0.90 → REVIEW
  > 0.90  → BLOCK
        │
        ▼
HTTP Response (immediate)
```

### Why XGBoost?
- Gradient boosted decision trees — state-of-the-art for tabular/structured data
- Handles class imbalance via `scale_pos_weight`
- Fast inference (~1ms per transaction)
- Produces calibrated probabilities via `predict_proba`

### Training-Serving Consistency
`app/features.py` is imported by both `ml/train.py` and `app/model.py`. This eliminates **training-serving skew** — the most common production ML failure mode.

---

## 3. API Layer

### Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/predict` | Fraud detection inference |
| `GET` | `/health` | Kubernetes **liveness** probe |
| `GET` | `/ready` | Kubernetes **readiness** probe |
| `GET` | `/model` | Model metadata + active thresholds |
| `GET` | `/metrics` | Prometheus metrics scrape endpoint |

### Stateless Design
Each FastAPI pod:
- Loads `model.pkl` independently at startup
- Holds no session state between requests
- Is safe to run behind a load balancer with N replicas
- Can be killed and replaced without data loss

---

## 4. Edge Layer — NGINX Ingress (API Gateway)

### Why an Ingress Controller?

Without it: `kubectl port-forward` — single connection, not scalable.  
With it: external traffic enters Kubernetes through a single controlled entry point.

### Responsibilities

| Feature | How |
|---------|-----|
| Load balancing | Routes across all healthy FastAPI pods (round-robin) |
| Health-based routing | Skips pods that fail `/ready` |
| Rate limiting | `nginx.ingress.kubernetes.io/limit-rps` annotation |
| Path routing | `/predict` → fraud-api Service |
| TLS termination | Optional: self-signed cert in Kind |

### Traffic Flow

```
External Client
      │
      ▼
NGINX Ingress Controller Pod
      │  (reads Ingress resource from K8s API)
      ▼
Kubernetes Service (ClusterIP)
      │  (kube-proxy + iptables routes)
      ▼
FastAPI Pod Pool (any healthy replica)
```

---

## 5. Horizontal Pod Autoscaler (HPA)

```
FastAPI Deployment
      │
      ▼
HPA Controller watches:
  • CPU utilization → scale up if > 60%
  • Memory usage
      │
      ▼
Adjusts replica count: 2 → 10 (automatically)
```

### Why HPA Matters
- **Burst traffic**: Black Friday payment surge → pods scale up automatically
- **Fault tolerance**: If a pod crashes, HPA ensures minimum replicas are maintained
- **Cost efficiency**: Scale down during low traffic (important when moving to cloud)

---

## 6. Kafka Pipeline (Async)

```
FastAPI Pod  ──asyncio.create_task()──►  Kafka Producer
                                              │
                                              ▼
                                    Topic: fraud-transactions
                                         Partition 0
                                         Partition 1
                                              │
                                              ▼
                                    Kafka Consumer Group
                                              │
                                              ▼
                                    Analytics / Alerts / Storage
```

### Key Concepts

| Concept | Role in this system |
|---------|---------------------|
| **Producer** | FastAPI pod sends fraud event after inference |
| **Topic** | `fraud-transactions` — ordered log of all events |
| **Partition** | Parallel processing lanes within the topic |
| **Consumer** | Separate service reads events for analytics |
| **Consumer Group** | Multiple consumer instances share the topic load |
| **Offset** | Position tracker — consumers restart from last offset on crash |

### Why Fire-and-Forget?
The HTTP response is returned **before** Kafka publish completes. `asyncio.create_task()` schedules the Kafka publish as a background coroutine. This means Kafka unavailability **never affects fraud decision latency**.

---

## 7. CI/CD Pipeline (Jenkins + Argo CD)

```
Developer git push
         │
         ▼
    Jenkins CI
    ┌────────────────────────────────────────┐
    │ 1. Checkout                            │
    │ 2. python -m venv + pip install        │
    │ 3. python ml/train.py                  │
    │ 4. pytest tests/                       │
    │ 5. docker build                        │
    │ 6. trivy image scan (CRITICAL/HIGH)    │
    │ 7. docker push → GHCR                  │
    │ 8. sed image tag in GitOps values.yaml │
    │ 9. git push GitOps repo                │
    └────────────────────────────────────────┘
         │
         ▼
    GitOps Repo (helm/fraud-api/values.yaml)
    image:
      tag: "v2-abc1234"      ← Jenkins updated this
         │
         ▼
    Argo CD detects diff (drift)
         │
         ▼
    Argo CD renders Helm chart
         │
         ▼
    kubectl apply (rolling update)
         │
         ▼
    New pods start (readiness probe waits for model.pkl load)
         │
         ▼
    Old pods terminate (zero downtime)
```

### Jenkins vs Argo CD — Responsibility Split

| Tool | Question It Answers |
|------|---------------------|
| **Jenkins** | "What should happen when code changes?" |
| **Argo CD** | "What should be running in Kubernetes right now?" |

Jenkins is one-shot triggered by events. Argo CD continuously reconciles the cluster toward the desired Git state.

---

## 8. Helm Chart Structure

```
helm/fraud-api/
├── Chart.yaml          ← name, version, appVersion
├── values.yaml         ← defaults (image, replicas, resources, thresholds)
└── templates/
    ├── deployment.yaml ← FastAPI pods
    ├── service.yaml    ← ClusterIP service
    ├── configmap.yaml  ← REVIEW_THRESHOLD, BLOCK_THRESHOLD, KAFKA env vars
    ├── hpa.yaml        ← HPA: 2-10 replicas, 60% CPU target
    └── ingress.yaml    ← NGINX Ingress routing
```

### Key `values.yaml` fields

```yaml
image:
  repository: ghcr.io/user/ml-ticket-prioritizer
  tag: xgb-v1

replicaCount: 2

autoscaling:
  enabled: true
  minReplicas: 2
  maxReplicas: 10
  targetCPUUtilizationPercentage: 60

ingress:
  enabled: true
  className: nginx
  host: fraud-api.local

env:
  REVIEW_THRESHOLD: "0.60"
  BLOCK_THRESHOLD: "0.90"
  KAFKA_ENABLED: "false"
```

---

## 9. Kubernetes Resource Map

```
Namespace: ml-platform
│
├── Deployment: fraud-api
│   ├── ReplicaSet (managed by Deployment)
│   │   ├── Pod 1 (FastAPI + XGBoost)
│   │   ├── Pod 2
│   │   └── Pod N
│   ├── livenessProbe  → GET /health  (is the process alive?)
│   └── readinessProbe → GET /ready   (is model loaded and ready?)
│
├── HPA: fraud-api-hpa
│   └── Watches CPU → scales Deployment replicas
│
├── Service: fraud-api (ClusterIP)
│   └── Routes to all healthy Deployment pods
│
├── Ingress: fraud-api-ingress
│   └── Routes /predict, /metrics → fraud-api Service
│
├── ConfigMap: fraud-api-config
│   └── REVIEW_THRESHOLD, BLOCK_THRESHOLD, KAFKA_TOPIC
│
├── StatefulSet: kafka
│   └── Service: kafka (headless)
│
├── Deployment: kafka-consumer
│
├── Deployment: prometheus
└── Deployment: grafana
```

---

## 10. Observability

### Metrics collected

| Metric | Source | Description |
|--------|--------|-------------|
| `http_requests_total` | Instrumentator | All HTTP requests by status |
| `http_request_duration_seconds` | Instrumentator | End-to-end HTTP latency |
| `fraud_decisions_total{decision}` | Custom | APPROVE/REVIEW/BLOCK counts |
| `fraud_inference_latency_seconds` | Custom | XGBoost inference time histogram |
| `kafka_fraud_events_produced_total` | Custom | Events published to Kafka |
| `kube_pod_container_resource_usage` | kube-state-metrics | Pod CPU/memory |

### Flow

```
FastAPI /metrics
        │
        ▼
Prometheus (pulls every 15s)
        │
        ▼
Grafana dashboard:
  • Request rate per pod
  • BLOCK/REVIEW/APPROVE distribution
  • Inference latency p50/p95/p99
  • HPA scaling events
  • Kafka lag
```

---

## 11. Terraform Scope

Terraform manages **infrastructure** — what platform resources should exist:

| Resource | Terraform manages |
|----------|-------------------|
| Kind cluster | cluster creation config |
| Namespace `ml-platform` | `kubernetes_namespace` |
| Argo CD Helm release | `helm_release` (bootstrap) |
| Prometheus stack | `helm_release` |
| NGINX Ingress | `helm_release` |

Terraform does **NOT** manage application deployments — that is Argo CD's job.

```
Terraform → "Does the platform exist?"
Argo CD   → "Is the right version of the app running?"
```

---

## 12. Complete Request Lifecycle

```
1. Client sends POST /predict with transaction JSON
2. NGINX Ingress receives request, picks a healthy FastAPI pod
3. Pydantic validates: amount > 0, hour 0-23, required fields present
4. Feature engineering converts 7 raw fields → 8 numeric features
5. XGBoost infers P(fraud) in ~1-5ms
6. Decision engine applies thresholds → APPROVE/REVIEW/BLOCK
7. HTTP 200 response returned immediately to client
8. asyncio.create_task() publishes Kafka event in background
9. Prometheus counters incremented (decisions, latency)
10. Kafka consumer reads event for analytics
```

---

## 13. Zero-Cost Component Map

| Component | Tool | Cost |
|-----------|------|------|
| Application | FastAPI + Python | Free |
| ML model | XGBoost | Free |
| Container runtime | Docker | Free |
| Local Kubernetes | Kind | Free |
| CI system | Jenkins (Docker) | Free |
| Container registry | GHCR | Free |
| GitOps | Argo CD | Free |
| Package manager | Helm | Free |
| API Gateway | NGINX Ingress | Free |
| Autoscaling | Kubernetes HPA | Free |
| Message broker | Apache Kafka | Free |
| Metrics | Prometheus | Free |
| Dashboards | Grafana | Free |
| IaC | Terraform CE | Free |
| **Total** | | **$0** |
