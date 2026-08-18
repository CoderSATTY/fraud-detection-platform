# Run Guide — Credit Card Fraud Detection Platform

> **Prerequisites** — install once on your machine

| Tool | Install command |
|------|----------------|
| Python 3.11+ | `sudo apt install python3.11` |
| Docker | [docs.docker.com/engine/install](https://docs.docker.com/engine/install/) |
| kubectl | `sudo snap install kubectl --classic` |
| Kind | `go install sigs.k8s.io/kind@v0.22.0` |
| Helm | `curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 \| bash` |
| Trivy | `sudo apt install trivy` |

---

## Phase 1 — ML Model + FastAPI (local Python)

### 1. Set up virtual environment

```bash
cd fraud-detection-platform
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Train the XGBoost model

Generates 60,000 synthetic transactions (~2% fraud), trains XGBoost, saves `ml/model.pkl`.

```bash
python ml/train.py
```

Expected output:
```
Generating synthetic fraud dataset ...
Dataset: 60,000 transactions | 1,200 fraud (2.0%)

Classification Report:
              precision    recall  f1-score
       Legit       0.99      0.99      0.99
       Fraud       0.87      0.85      0.86

ROC-AUC: 0.9812

Model saved → ml/model.pkl
```

### 3. Start the API

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 4. Test the endpoints

```bash
# Liveness
curl http://localhost:8000/health

# Readiness (confirms model loaded)
curl http://localhost:8000/ready

# Model metadata + thresholds
curl http://localhost:8000/model

# Fraud prediction — suspicious transaction
curl -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{
    "transaction_id": "txn_93821",
    "amount": 9500.00,
    "category": "shopping_net",
    "state": "CA",
    "transaction_hour": 3,
    "distance_from_last_transaction": 4500.0,
    "device_type": "mobile"
  }'

# Expected response
# {"transaction_id":"txn_93821","fraud_probability":0.97,"decision":"BLOCK","model_version":"xgb-v1"}

# Legitimate transaction
curl -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{
    "transaction_id": "txn_00123",
    "amount": 22.50,
    "category": "grocery_pos",
    "state": "TX",
    "transaction_hour": 14,
    "distance_from_last_transaction": 1.5,
    "device_type": "desktop"
  }'

# Interactive docs
open http://localhost:8000/docs
```

### 5. Run tests

```bash
pytest tests/ -v
```

---

## Phase 2 — Docker

### Build the image

```bash
docker build -t fraud-api:xgb-v1 .
```

> **Note**: `ml/model.pkl` must exist before building (run `python ml/train.py` first).
> The Dockerfile copies `ml/` into the image so each container is self-contained.

### Run the container

```bash
docker run -p 8000:8000 fraud-api:xgb-v1
```

### Verify

```bash
curl http://localhost:8000/health
curl http://localhost:8000/ready    # waits until XGBoost model is loaded
```

---

## Phase 3 — Kind + Kubernetes

### Create the cluster

```bash
kind create cluster --name ml-platform
kubectl cluster-info --context kind-ml-platform
```

### Create namespace

```bash
kubectl create namespace ml-platform
```

### Load image into Kind

```bash
kind load docker-image fraud-api:xgb-v1 --name ml-platform
```

### Apply basic manifests (before Helm)

```bash
kubectl apply -f k8s/deployment.yaml -n ml-platform
kubectl apply -f k8s/service.yaml    -n ml-platform

# Watch pods come up — readiness probe fires GET /ready
kubectl get pods -n ml-platform -w

# Check liveness and readiness
kubectl describe pod <pod-name> -n ml-platform

# Port-forward to test directly
kubectl port-forward svc/fraud-api 8000:8000 -n ml-platform
```

### Understand the probes

```yaml
# The Dockerfile/Deployment sets these:
livenessProbe:
  httpGet: { path: /health, port: 8000 }   # is the process alive?
  initialDelaySeconds: 10

readinessProbe:
  httpGet: { path: /ready, port: 8000 }    # is model.pkl loaded?
  initialDelaySeconds: 15
```

Traffic only reaches a pod after `/ready` returns 200. This means no requests hit a pod before XGBoost is ready.

---

## Phase 4 — Helm (with HPA + Ingress)

### Install NGINX Ingress Controller first

```bash
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
helm repo update
helm install ingress-nginx ingress-nginx/ingress-nginx \
  --namespace ingress-nginx --create-namespace
```

### Install fraud-api via Helm

```bash
helm install fraud-api helm/fraud-api/ \
  --namespace ml-platform \
  --set image.tag=xgb-v1 \
  --set replicaCount=2 \
  --set autoscaling.enabled=true
```

### Watch the HPA in action

```bash
# See current HPA status
kubectl get hpa -n ml-platform

# Generate load (in a separate terminal) to trigger scaling
kubectl run load-test --image=busybox --restart=Never -n ml-platform -- \
  /bin/sh -c "while true; do wget -q -O- http://fraud-api:8000/health > /dev/null; done"

# Watch pods scale up
kubectl get pods -n ml-platform -w
```

### Upgrade (simulates what Argo CD does)

```bash
helm upgrade fraud-api helm/fraud-api/ \
  --namespace ml-platform \
  --set image.tag=xgb-v2

# Watch rolling update (zero downtime)
kubectl rollout status deployment/fraud-api -n ml-platform
```

### Tune decision thresholds without rebuilding

```bash
helm upgrade fraud-api helm/fraud-api/ \
  --namespace ml-platform \
  --set env.REVIEW_THRESHOLD=0.55 \
  --set env.BLOCK_THRESHOLD=0.85
```

---

## Phase 5 — Argo CD (GitOps)

### Install Argo CD

```bash
kubectl create namespace argocd
kubectl apply -n argocd \
  -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

# Wait for all pods
kubectl wait --for=condition=Ready pod --all -n argocd --timeout=180s
```

### Access the UI

```bash
kubectl port-forward svc/argocd-server 8080:443 -n argocd
```

Get admin password:

```bash
kubectl get secret argocd-initial-admin-secret -n argocd \
  -o jsonpath="{.data.password}" | base64 -d && echo
```

Open https://localhost:8080 → login `admin` + above password.

### Apply Application manifest

```bash
kubectl apply -f argocd/application.yaml
```

This creates an Argo CD Application that:
- Watches: `helm/fraud-api/` in your GitOps repo
- Deploys to: `ml-platform` namespace
- Syncs automatically when Git changes

### Trigger a deployment via Git

```bash
# Edit the GitOps repo
vim helm/fraud-api/values.yaml
# Change: tag: xgb-v1 → tag: xgb-v2

git add helm/fraud-api/values.yaml
git commit -m "deploy: update fraud-api to xgb-v2"
git push origin main
```

Argo CD detects the change within 3 minutes (or click **Sync** in UI) and performs a rolling update automatically.

---

## Phase 6 — Jenkins CI + GHCR

### Run Jenkins in Docker

```bash
docker run -d \
  --name jenkins \
  -p 8081:8080 \
  -p 50000:50000 \
  -v jenkins_home:/var/jenkins_home \
  -v /var/run/docker.sock:/var/run/docker.sock \
  jenkins/jenkins:lts-jdk17
```

### Initial setup

```bash
# Get unlock password
docker exec jenkins cat /var/jenkins_home/secrets/initialAdminPassword
```

Open http://localhost:8081 → paste password → install suggested plugins.

### Add credentials

**Manage Jenkins → Credentials → Global → Add Credential**:

| Credential ID | Type | Value |
|--------------|------|-------|
| `GHCR_TOKEN` | Secret text | GitHub PAT: `write:packages` scope |
| `GITOPS_TOKEN` | Secret text | GitHub PAT: `repo` scope |

### Create pipeline job

1. **New Item** → Pipeline → name: `fraud-api-ci`
2. **Pipeline script from SCM** → Git → your repo URL
3. **Script Path**: `Jenkinsfile`
4. Save → **Build Now**

### What Jenkins does

```
Checkout → pip install → python ml/train.py → pytest
       → docker build → trivy scan → docker push ghcr.io/...
       → sed image tag in GitOps values.yaml → git push
```

After `git push`, Argo CD picks up the new tag → rolling update fires.

---

## Phase 7 — Kafka

### Deploy Kafka inside Kind

```bash
kubectl apply -f kafka/deployment.yaml -n ml-platform
kubectl apply -f kafka/service.yaml    -n ml-platform

# Wait for broker to be ready
kubectl rollout status statefulset/kafka -n ml-platform
```

### Enable Kafka in the fraud API

```bash
helm upgrade fraud-api helm/fraud-api/ --namespace ml-platform \
  --set env.KAFKA_ENABLED=true \
  --set env.KAFKA_BOOTSTRAP_SERVERS=kafka:9092 \
  --set env.KAFKA_TOPIC=fraud-transactions
```

### Deploy the consumer

```bash
kubectl apply -f consumer/deployment.yaml -n ml-platform
```

### Watch events flow

```bash
# Watch consumer logs
kubectl logs -f deployment/fraud-consumer -n ml-platform

# Send a suspicious transaction
curl -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{
    "transaction_id": "txn_stream_001",
    "amount": 7500.00,
    "category": "misc_net",
    "state": "NY",
    "transaction_hour": 2,
    "distance_from_last_transaction": 3200.0,
    "device_type": "mobile"
  }'

# Consumer receives the Kafka event within milliseconds,
# but the HTTP response above was already returned to the client.
```

---

## Phase 8 — Prometheus + Grafana

### Install kube-prometheus-stack

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

helm install monitoring prometheus-community/kube-prometheus-stack \
  --namespace ml-platform \
  --set grafana.adminPassword=admin
```

### Verify Prometheus scrapes FastAPI

```bash
kubectl port-forward svc/monitoring-prometheus-operated 9090:9090 -n ml-platform
```

Open http://localhost:9090 → query:
- `fraud_decisions_total` — see APPROVE/REVIEW/BLOCK counters
- `fraud_inference_latency_seconds_bucket` — latency histogram
- `kafka_fraud_events_produced_total` — Kafka publish count

### Access Grafana

```bash
kubectl port-forward svc/monitoring-grafana 3000:80 -n ml-platform
```

Open http://localhost:3000 → login `admin` / `admin`.  
Import dashboard from `monitoring/grafana-dashboard.json`.

### Key panels to build

| Panel | Query |
|-------|-------|
| Decisions/sec | `rate(fraud_decisions_total[1m])` |
| Block rate | `rate(fraud_decisions_total{decision="BLOCK"}[5m])` |
| Inference p95 latency | `histogram_quantile(0.95, fraud_inference_latency_seconds_bucket)` |
| Replicas | `kube_deployment_status_replicas{deployment="fraud-api"}` |
| HPA target vs actual | `kube_horizontalpodautoscaler_status_current_replicas` |

---

## Phase 9 — Terraform

### Install Terraform

```bash
sudo snap install terraform --classic
```

### Bootstrap the platform

```bash
cd terraform/
terraform init
terraform plan
terraform apply
```

Terraform provisions:
- Kind cluster
- Namespace `ml-platform`
- NGINX Ingress Helm release
- Argo CD Helm release (bootstrap only)
- Prometheus stack Helm release

**Argo CD then takes over** to deploy the fraud-api application. Terraform never touches the application — only the platform.

---

## Quick Reference

```bash
# Phase 1 — Local dev
source .venv/bin/activate
python ml/train.py
uvicorn app.main:app --reload
pytest tests/ -v

# Phase 2 — Docker
docker build -t fraud-api:xgb-v1 .
docker run -p 8000:8000 fraud-api:xgb-v1

# Phase 3 — Kubernetes
kind create cluster --name ml-platform
kind load docker-image fraud-api:xgb-v1 --name ml-platform
kubectl apply -f k8s/ -n ml-platform

# Phase 4 — Helm
helm install fraud-api helm/fraud-api/ -n ml-platform
kubectl get hpa -n ml-platform

# Phase 5 — Argo CD
kubectl port-forward svc/argocd-server 8080:443 -n argocd

# Phase 6 — Jenkins
docker run -d -p 8081:8080 -v /var/run/docker.sock:/var/run/docker.sock jenkins/jenkins:lts-jdk17

# Phase 7 — Kafka
kubectl apply -f kafka/ -n ml-platform
kubectl logs -f deployment/fraud-consumer -n ml-platform

# Phase 8 — Prometheus + Grafana
kubectl port-forward svc/monitoring-prometheus-operated 9090:9090 -n ml-platform
kubectl port-forward svc/monitoring-grafana 3000:80 -n ml-platform

# Phase 9 — Terraform
cd terraform && terraform apply
```

---

## Decision Threshold Tuning

Thresholds are configurable without a code change or rebuild:

```bash
# Via Helm (updates ConfigMap, pods reload env vars)
helm upgrade fraud-api helm/fraud-api/ -n ml-platform \
  --set env.REVIEW_THRESHOLD=0.55 \
  --set env.BLOCK_THRESHOLD=0.88

# Via kubectl (directly edit ConfigMap)
kubectl edit configmap fraud-api-config -n ml-platform
# Then restart pods to pick up new env:
kubectl rollout restart deployment/fraud-api -n ml-platform
```

| Threshold | Effect |
|-----------|--------|
| Lower `BLOCK_THRESHOLD` | Block more transactions (higher security, more false positives) |
| Raise `REVIEW_THRESHOLD` | Fewer transactions flagged for review |
| Both equal | Binary APPROVE/BLOCK only |
