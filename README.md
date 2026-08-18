<div align="center">
  <h1>🛡️ Sentinel</h1>
  <h3>High-Frequency MLOps Fraud Detection Platform</h3>
  <p>An enterprise-grade, event-driven microservices architecture built for real-time credit card fraud inference at scale.</p>

  <img src="https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white" />
  <img src="https://img.shields.io/badge/Kubernetes-326CE5?style=for-the-badge&logo=kubernetes&logoColor=white" />
  <img src="https://img.shields.io/badge/Apache_Kafka-231F20?style=for-the-badge&logo=apache-kafka&logoColor=white" />
  <img src="https://img.shields.io/badge/Terraform-7B42BC?style=for-the-badge&logo=terraform&logoColor=white" />
  <img src="https://img.shields.io/badge/Argo_CD-EF7B4D?style=for-the-badge&logo=argo&logoColor=white" />
  <img src="https://img.shields.io/badge/Jenkins-D24939?style=for-the-badge&logo=jenkins&logoColor=white" />
</div>

<br/>

## 📖 Overview

**Sentinel** is a production-ready Machine Learning Operations (MLOps) platform designed to ingest, process, and classify high-velocity transaction streams for credit card fraud detection. 

Unlike standard REST-based ML APIs, Sentinel utilizes an **asynchronous, event-driven architecture** via Apache Kafka. It offloads inference telemetry and downstream reporting entirely from the main request thread, guaranteeing sustained ultra-low latency (under 5ms per transaction) for the core FastAPI inference engine.

## 🚀 Key Features

* **Real-time ML Inference:** XGBoost model served via an ASGI FastAPI layer, optimized for tabular transaction classification.
* **Asynchronous Telemetry:** Apache Kafka event streams for decoupled, non-blocking telemetry logging and downstream analytics.
* **GitOps CI/CD Automation:** End-to-end pipeline using Jenkins for continuous integration/testing, and Argo CD for declarative, zero-downtime Kubernetes rolling updates.
* **Infrastructure as Code (IaC):** Automated cloud-native cluster provisioning (NGINX Ingress, Argo CD, Prometheus Stack) utilizing Terraform.
* **Full-Stack Observability:** Embedded custom Prometheus `ServiceMonitors` feeding into Grafana for real-time latency, throughput, and class-distribution dashboarding.

## 🛠️ Technology Stack

| Domain | Technologies |
| :--- | :--- |
| **Model / API** | Python, XGBoost, Scikit-Learn, FastAPI, Uvicorn, Pytest |
| **Event Streaming** | Apache Kafka, Zookeeper, `aiokafka` |
| **Orchestration** | Kubernetes (K8s), Helm, Docker, NGINX Ingress |
| **CI/CD (GitOps)** | Jenkins, Argo CD, Trivy (Security Scanning) |
| **Infrastructure** | Terraform, Kind (Kubernetes IN Docker) |
| **Observability** | Prometheus, Grafana, Kube-State-Metrics |

## 📂 Repository Structure

```text
.
├── app/                  # FastAPI Application (Endpoints, Schemas, Kafka Producer)
├── consumer/             # Background Kafka Consumer Daemon
├── ml/                   # Machine Learning model training scripts and pickle files
├── tests/                # Pytest suites for API and unit testing
├── helm/                 # Helm charts for dynamic Kubernetes packaging
├── k8s/                  # Kubernetes manifest YAMLs (Metrics, HPA, Configs)
├── kafka/                # Kafka & Zookeeper Kubernetes manifests
├── argocd/               # Argo CD Application deployment configurations
├── terraform/            # Infrastructure-as-Code for K8s provisioning
└── Jenkinsfile           # Jenkins Declarative Pipeline for CI/CD
```

## 📈 System Architecture Flow

1. **Client** hits the `NGINX Ingress Controller` with a transaction payload.
2. Request routes to a **FastAPI Pod** (Horizontally Auto-scaled via HPA).
3. FastAPI runs local **XGBoost Inference** (`model.pkl`).
4. FastAPI asynchronously fires the decision payload to **Apache Kafka**.
5. FastAPI returns a sub-5ms response to the **Client**.
6. The **Consumer Daemon** reads the Kafka topic for downstream analytics.
7. **Prometheus** scrapes metrics endpoint every 10s; **Grafana** visualizes the data.
