pipeline {
    agent any

    environment {
        REGISTRY      = "ghcr.io"
        GHCR_USER     = "CoderSATTY"
        IMAGE_NAME    = "fraud-api"
        IMAGE_FULL    = "${REGISTRY}/${GHCR_USER}/${IMAGE_NAME}"
        GITOPS_REPO   = "https://github.com/${GHCR_USER}/fraud-detection-platform.git"
        GITOPS_VALUES = "helm/fraud-api/values.yaml"
        IMAGE_TAG     = "xgb-v${BUILD_NUMBER}-${sh(script: 'git rev-parse --short HEAD', returnStdout: true).trim()}"
    }

    options {
        timestamps()
        timeout(time: 30, unit: "MINUTES")
        buildDiscarder(logRotator(numToKeepStr: "10"))
    }

    stages {
        stage("Checkout") {
            steps { checkout scm }
        }

        stage("Install Dependencies") {
            steps {
                sh """
                    python3 -m venv .venv
                    . .venv/bin/activate
                    pip install --upgrade pip
                    pip install --no-cache-dir -r requirements.txt
                """
            }
        }

        stage("Train ML Model") {
            steps {
                sh """
                    . .venv/bin/activate
                    python ml/train.py
                """
            }
        }

        stage("Run Tests") {
            steps {
                sh """
                    . .venv/bin/activate
                    pytest tests/ -v --tb=short --junitxml=test-results.xml
                """
            }
            post {
                always { junit "test-results.xml" }
            }
        }

        stage("Docker Build") {
            steps {
                sh "docker build -t ${IMAGE_FULL}:${IMAGE_TAG} -t ${IMAGE_FULL}:latest ."
            }
        }

        stage("Security Scan") {
            steps {
                sh """
                    trivy image --severity HIGH,CRITICAL --exit-code 1 --no-progress ${IMAGE_FULL}:${IMAGE_TAG}
                """
            }
        }

        stage("Push to GHCR") {
            steps {
                withCredentials([string(credentialsId: "GHCR_TOKEN", variable: "TOKEN")]) {
                    sh """
                        echo "\${TOKEN}" | docker login ${REGISTRY} -u ${GHCR_USER} --password-stdin
                        docker push ${IMAGE_FULL}:${IMAGE_TAG}
                        docker push ${IMAGE_FULL}:latest
                    """
                }
            }
        }

        stage("Update GitOps Repo") {
            steps {
                withCredentials([string(credentialsId: "GITOPS_TOKEN", variable: "TOKEN")]) {
                    sh """
                        git clone https://\${TOKEN}@${GITOPS_REPO.replace("https://", "")} gitops-repo
                        sed -i 's|tag: .*|tag: "${IMAGE_TAG}"|' gitops-repo/${GITOPS_VALUES}
                        cd gitops-repo
                        git config user.email "jenkins@ci.local"
                        git config user.name "Jenkins CI"
                        git add ${GITOPS_VALUES}
                        git commit -m "ci: update image to ${IMAGE_TAG} [build ${BUILD_NUMBER}]"
                        git push origin main
                        cd ..
                        rm -rf gitops-repo
                    """
                }
            }
        }
    }

    post {
        always {
            sh "docker rmi ${IMAGE_FULL}:${IMAGE_TAG} || true"
            sh "docker rmi ${IMAGE_FULL}:latest || true"
            cleanWs()
        }
    }
}
