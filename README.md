# Atunbi 🧠

**Track 1: MemoryAgent** | [Qwen Cloud Global AI Hackathon](https://qwencloud-hackathon.devpost.com/)

Atunbi (Yoruba for "reborn" or "brought back to life") is a cognitive memory architecture for AI agents. Moving beyond naive RAG, Atunbi provides persistent, decaying, and consolidating memory tiers (Working, Episodic, Semantic) that allow agents to learn, adapt, and "dream" across multi-turn, cross-session interactions.

## 🏗️ Architecture & Tech Stack

Atunbi is deployed on **Alibaba Cloud** and powered by **Qwen Cloud APIs**.

*   **Backend:** FastAPI (Python) deployed via Docker on **Alibaba Cloud ECS**.
*   **Database:** PostgreSQL with `pgvector` for hybrid semantic and keyword search.
*   **AI Engine:** Qwen Cloud APIs for reasoning, memory consolidation, and the "Dream Phase".
*   **Frontend:** Next.js (React) deployed on Vercel.
*   **CI/CD:** GitHub Actions for automated testing and zero-downtime deployments.

## 🚀 Local Development (Backend)

To run the walking skeleton locally:

```bash
# 1. Navigate to the backend
cd backend

# 2. Create and activate the virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run the FastAPI server
uvicorn main:app --reload
```

The API will be available at `http://127.0.0.1:8000/docs`.

## ☁️ Alibaba Cloud Deployment Proof

This project utilizes Alibaba Cloud ECS for backend compute, satisfying the hackathon's deployment requirements.

*   **Deployment Region:** UK (London)
*   **Infrastructure:** Dockerized FastAPI application running on Ubuntu 22.04 via ECS (`ecs.t6-c2m1.large`).
*   **CI/CD Pipeline:** GitHub Actions automatically builds the AMD64 Docker image and SSHs into the ECS instance to perform zero-downtime container swaps on every push to `main`.

👉 **[View the Deployment Pipeline & Infrastructure Proof here](./docs/proof-of-deployment.md)**

## 📄 License

This project is open source and available under the [MIT License](LICENSE).
