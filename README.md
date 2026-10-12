# 🎬 MOVIES TMDA — Catálogo de Filmes Full-Stack

> Plataforma full-stack de catálogo de filmes com área Premium, pagamentos, e-mails transacionais e assistente virtual com IA — rodando em **Kubernetes**.

![Angular](https://img.shields.io/badge/Angular-22-DD0031?logo=angular&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-Python_3.12-009688?logo=fastapi&logoColor=white)
![MySQL](https://img.shields.io/badge/MySQL-8-4479A1?logo=mysql&logoColor=white)
![Kubernetes](https://img.shields.io/badge/Kubernetes-k3d-326CE5?logo=kubernetes&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-multi--stage-2496ED?logo=docker&logoColor=white)
![NGINX](https://img.shields.io/badge/NGINX-Ingress-009639?logo=nginx&logoColor=white)

---

## 📋 Sobre o projeto

O **MOVIES TMDA** é uma aplicação full-stack onde o usuário busca filmes (via API do TMDB), monta sua lista pessoal (*quero ver*, *assistindo*, *assistido*) e pode assinar um plano **Premium** com conteúdo exclusivo. O projeto foi construído como estudo aprofundado de **arquitetura em microsserviços sobre Kubernetes**, integrando pagamentos, e-mails, geração de documentos e um chatbot com Inteligência Artificial.

Todo o ambiente roda em um cluster **Kubernetes local (k3d)**, com frontend e backend em containers separados, banco de dados persistente e roteamento via **NGINX Ingress**.

---

## ✨ Funcionalidades

### 👤 Autenticação & Segurança
- Cadastro com **double opt-in** (confirmação por e-mail)
- Login por **usuário OU e-mail**
- Senhas com **bcrypt** + verificação de vazamento via **HIBP** (Have I Been Pwned)
- **JWT** para sessões · proteção **anti-robô** (Cloudflare Turnstile)
- Fluxo de **"Esqueci minha senha"** por e-mail

### 🎥 Catálogo
- Busca de filmes em tempo real (API do TMDB)
- Vitrine de destaques (em alta, lançamentos, populares, 2027, novembro)
- Detalhes com sinopse, trailers e galeria de imagens
- Lista pessoal com status (quero ver / assistindo / assistido)

### 💳 Assinatura Premium
- Pagamento via **PayPal (Sandbox)** — Orders API v2
- **Reembolso/estorno** com um clique
- **Comprovante em PDF** gerado no servidor (fpdf2) e anexado por e-mail
- Histórico de transações (livro-razão) com exclusão

### 🤖 Assistente Virtual (IA)
- Chatbot integrado com **Groq** (modelo GPT-OSS-20B)
- **RAG** (Retrieval-Augmented Generation): o bot conhece o catálogo real e os dados da conta
- Anti-alucinação: nunca inventa filmes ou políticas inexistentes

### 📧 E-mails & Conformidade
- E-mails transacionais via **Mailtrap** (confirmação, reset, pagamento, estorno)
- Formulário de contato
- Políticas de **Privacidade, Assinatura e Cancelamento** (LGPD / CDC)

---

## 🛠️ Stack

| Camada | Tecnologias |
|---|---|
| **Frontend** | Angular 22 · TypeScript · Tailwind CSS v4 · Signals |
| **Backend** | Python 3.12 · FastAPI · SQLAlchemy 2.0 · Uvicorn |
| **Banco** | MySQL 8 (StatefulSet) · phpMyAdmin |
| **Infra** | Docker (multi-stage) · Kubernetes (k3d) · NGINX Ingress |
| **Integrações** | TMDB · PayPal Sandbox · Mailtrap · Groq (IA) · Cloudflare Turnstile · HIBP |

---

## 🏗️ Arquitetura

```
                        ┌─────────────────────────────┐
   Navegador  ───────▶  │     NGINX Ingress (k3d)      │
                        └──────────────┬──────────────┘
                              /         │         /api
                        ┌─────▼─────┐   │   ┌──────▼───────┐
                        │ Frontend  │   │   │   Backend     │
                        │ Angular + │   │   │  FastAPI      │
                        │  NGINX    │   │   │ (2 réplicas)  │
                        └───────────┘   │   └──────┬───────┘
                                        │          │
                                 ┌──────▼──────┐   │   APIs externas:
                                 │  MySQL 8    │◀──┘   TMDB · PayPal
                                 │ StatefulSet │       Mailtrap · Groq
                                 └─────────────┘
```

---

## 🚀 Como rodar

### Pré-requisitos
- Docker · k3d · kubectl
- Contas (gratuitas) para as integrações: TMDB, PayPal Developer, Mailtrap, Groq

### 1. Criar o cluster
```bash
k3d cluster create painel-obs --port "8090:80@loadbalancer"
```

### 2. Criar os Secrets (as chaves ficam FORA do código)
```bash
kubectl create secret generic mysql-secret     --from-literal=MYSQL_USER=... --from-literal=MYSQL_PASSWORD=... --from-literal=MYSQL_DATABASE=catalogo
kubectl create secret generic tmdb-secret      --from-literal=TMDB_API_KEY=...
kubectl create secret generic jwt-secret       --from-literal=JWT_SECRET=...
kubectl create secret generic turnstile-secret --from-literal=TURNSTILE_SECRET=...
kubectl create secret generic groq-secret      --from-literal=GROQ_API_KEY=...
kubectl create secret generic mailtrap-secret  --from-literal=MAIL_HOST=... --from-literal=MAIL_USER=... --from-literal=MAIL_PASS=...
kubectl create secret generic paypal-secret    --from-literal=PAYPAL_CLIENT_ID=... --from-literal=PAYPAL_SECRET=...
```

### 3. Aplicar os manifestos e fazer o deploy
```bash
kubectl apply -f k8s/
./deploy.sh ambos          # builda e sobe backend + frontend
```

### 4. Acessar
```
http://localhost:8090
```

> 💡 Durante o desenvolvimento do frontend, use `npx ng serve --proxy-config proxy.conf.json` (hot reload em `localhost:4200`).

---

## 📁 Estrutura

```
.
├── backend/              # FastAPI (API, autenticação, pagamentos, IA)
│   ├── app/main.py
│   ├── requirements.txt
│   └── Dockerfile        # imagem Python slim
├── frontend/             # Angular (SPA)
│   ├── src/app/
│   └── Dockerfile        # multi-stage: build Angular → NGINX
├── k8s/                  # manifestos Kubernetes (deployments, services, ingress, secrets)
└── deploy.sh             # script de build + deploy (front | back | ambos)
```

---

## 🧠 Destaques técnicos

- **RAG (Retrieval-Augmented Generation):** o chatbot recebe os filmes reais do catálogo e os dados da conta injetados em contexto antes de responder — evitando alucinações.
- **Multi-stage Docker build:** a imagem do frontend compila o Angular numa etapa e serve só os arquivos estáticos via NGINX, deixando a imagem final enxuta.
- **Cache de camadas:** `package.json` e `requirements.txt` são copiados antes do código para reaproveitar a instalação de dependências entre builds.
- **Segurança por padrão:** segredos nunca ficam no código (via Secrets do k8s + `os.getenv`); proteção contra IDOR, tabnabbing, enumeração de usuários e injeção de HTML.
- **Dev vs Produção:** `ng serve` (hot reload) no desenvolvimento; imagem imutável + réplicas no Kubernetes em produção.

---

## 📄 Licença & Créditos

Projeto desenvolvido para **fins educativos e de portfólio**.

Este produto usa a API do **TMDB**, mas não é endossado nem certificado pelo TMDB.
Pagamentos processados em ambiente **sandbox** do PayPal (sem cobrança real).
Imagens e dados de filmes pertencem a seus respectivos titulares, conforme a **Lei nº 9.610/98**.

© 2026 · Santhiago · All rights reserved.