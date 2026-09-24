# AI Client Outreach

AI-powered B2B client research and personalized outreach platform.

## Current Phase

**Phase 1:** Excel Import + Validation + Company Database

## Tech Stack

- **Frontend:** React, Vite, Tailwind CSS
- **Backend:** Python 3.12+, FastAPI, Uvicorn, Motor (Async MongoDB), BeautifulSoup4, httpx
- **Database:** MongoDB
- **Excel:** openpyxl

## Getting Started

### Prerequisites

- Python 3.10+
- Node.js 18+ (for frontend)
- MongoDB running locally on port 27017

### Backend (Python FastAPI)

```bash
cd backend
# Windows:
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt

# Start backend server:
python run.py
```

Server runs on `http://localhost:5000`. API docs available at `http://localhost:5000/docs`.

*(Note: The previous Node.js backend codebase is safely archived in `backend_node_backup/`)*

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend runs on `http://localhost:5173`.

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/health` | Health check |
| POST | `/api/import/excel` | Upload & validate Excel |
| GET | `/api/import/:id` | Get import batch details |
| POST | `/api/import/:id/confirm` | Confirm & execute import |
| GET | `/api/companies` | List companies (paginated, searchable) |
| POST | `/api/companies/:id/crawl` | Trigger website crawl |
| GET | `/api/companies/:id/crawl` | Get crawl status |
| GET | `/api/companies/:id/pages` | Get crawled pages |
| POST | `/api/companies/:id/research` | Run AI research synthesis |
| GET | `/api/companies/:id/research` | Get synthesized company research |
| GET | `/api/companies/:id/contacts` | List contacts |
| POST | `/api/companies/:id/contacts` | Add contact |
| POST | `/api/companies/:id/contacts/discover` | Discover decision makers |
| GET | `/api/companies/:id/contacts/pattern` | Get email pattern analysis |
| POST | `/api/companies/:id/contacts/apply-pattern` | Apply pattern to contacts |
| POST | `/api/companies/:id/outreach/generate` | Generate 3-step outreach sequence |
| POST | `/api/companies/:id/outreach/schedule` | Schedule sequence steps |
| GET | `/api/outreach/all` | Global outbox |
| GET | `/api/outreach/records` | Tracking records |
| GET | `/api/outreach/stats` | Outreach statistics |
| GET | `/api/outreach/export` | Export outreach records to Excel |
| GET | `/api/settings` | Get AI & SMTP settings |
| POST | `/api/settings` | Update settings |
| POST | `/api/settings/test-smtp` | Test SMTP credentials |

## Commands

```bash
# Backend
cd backend
.\venv\Scripts\python run.py                # Start dev server on port 5000
.\venv\Scripts\python -m pytest -v          # Run pytest test suite

# Frontend
cd frontend
npm run dev          # Start dev server
npm run build        # Production build
```
