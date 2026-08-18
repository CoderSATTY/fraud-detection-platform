terraform {
  required_providers {
    kind = {
      source  = "tehcyx/kind"
      version = "0.4.0"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.23.0"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "~> 2.11.0"
    }
  }
}

provider "kind" {}

resource "kind_cluster" "ml_platform" {
  name           = "ml-platform"
  wait_for_ready = true
}

provider "kubernetes" {
  host                   = kind_cluster.ml_platform.endpoint
  client_certificate     = kind_cluster.ml_platform.client_certificate
  client_key             = kind_cluster.ml_platform.client_key
  cluster_ca_certificate = kind_cluster.ml_platform.cluster_ca_certificate
}

provider "helm" {
  kubernetes {
    host                   = kind_cluster.ml_platform.endpoint
    client_certificate     = kind_cluster.ml_platform.client_certificate
    client_key             = kind_cluster.ml_platform.client_key
    cluster_ca_certificate = kind_cluster.ml_platform.cluster_ca_certificate
  }
}

resource "kubernetes_namespace" "ml_platform" {
  metadata {
    name = "ml-platform"
  }
}

resource "kubernetes_namespace" "monitoring" {
  metadata {
    name = "monitoring"
  }
}

resource "kubernetes_namespace" "argocd" {
  metadata {
    name = "argocd"
  }
}

resource "helm_release" "ingress_nginx" {
  name             = "ingress-nginx"
  repository       = "https://kubernetes.github.io/ingress-nginx"
  chart            = "ingress-nginx"
  namespace        = "ingress-nginx"
  create_namespace = true

  set {
    name  = "controller.hostNetwork"
    value = "true"
  }
  
  depends_on = [kind_cluster.ml_platform]
}

resource "helm_release" "prometheus" {
  name       = "monitoring"
  repository = "https://prometheus-community.github.io/helm-charts"
  chart      = "kube-prometheus-stack"
  namespace  = kubernetes_namespace.monitoring.metadata[0].name

  set {
    name  = "grafana.adminPassword"
    value = "admin"
  }

  depends_on = [kind_cluster.ml_platform, kubernetes_namespace.monitoring]
}

resource "helm_release" "argocd" {
  name       = "argocd"
  repository = "https://argoproj.github.io/argo-helm"
  chart      = "argo-cd"
  namespace  = kubernetes_namespace.argocd.metadata[0].name

  set {
    name  = "server.service.type"
    value = "ClusterIP"
  }

  depends_on = [kind_cluster.ml_platform, kubernetes_namespace.argocd]
}
