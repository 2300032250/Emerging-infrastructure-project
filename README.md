# CLOUD-225 — Emerging Infrastructure Project Maturity Assessment for Adoption Decisions

Batch / Team: **C2C-95** | Domain: **Cloud Infrastructure Design & Engineering**

This repository is organized into two folders:
- [`backend/`](./backend): Python FastAPI service, GitHub REST API & fixture ingestion with checkpoints, O2 reference pipeline + independent oracle, O3 popularity-independent sustainability indicators, O4 `scikit-learn` maintenance-continuity predictor, SQLite/PostgreSQL persistence, NT-1 to NT-5 security & negative-test campaign, and pytest acceptance suite.
- [`frontend/`](./frontend): React + Vite dashboard with **Decision-Maker View**, **Chapter 7 Validation & KPIs View**, and **Operator & NT-1..NT-5 Console**.

## Quick Start (Local Development)

### 1. Backend
```bash
cd backend
python -m venv .venv
# Windows PowerShell:
.venv\\Scripts\\Activate.ps1
pip install -r requirements.txt
pytest -v
python run_acceptance.py
uvicorn app.main:app --reload --port 8000
```

### 2. Frontend
```bash
cd frontend
npm install
npm run dev
```
Open `http://localhost:5173`. Vite proxies `/api`, `/health`, and `/metrics` to `http://127.0.0.1:8000`.

### 3. Docker Compose (PostgreSQL + Backend + Frontend)
```bash
docker compose up --build
```
"# Emerging-infrastructure" 
"# Emerging-infrastructure" 
"# Emerging-infrastructure" 
"# Emerging-infrastructure" 
