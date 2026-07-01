# SignalForge — Quick Start (Only Commands to Run the Project)

> **Prerequisites:** Python 3.14+, Node.js 20+, Git, Docker (optional)

---

## Step 1: Clone & Navigate

```bash
git clone https://github.com/dharmppp21/Worthy-One.git
cd "C:\Users\dharm\OneDrive\文档\Worthy One\signalforge_mvp\"
```

---

## Step 2: Start Backend (Terminal 1)

```powershell
cd backend
# Create venv (one time only)
python -m venv .venv

# Activate venv
.venv\Scripts\Activate.ps1

# Install dependencies (one time only)
pip install -r requirements.txt

# Delete old SQLite DB if migrations fail
Remove-Item -Force signforge.db -ErrorAction SilentlyContinue

# Run database migrations
.venv\Scripts\alembic.exe upgrade head

# Start the server
.venv\Scripts\uvicorn.exe app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

**What this does:**
- Creates isolated Python environment
- Installs FastAPI, SQLAlchemy, Pydantic, Docker SDK, K8s client, etc.
- Creates SQLite database with all tables (events, incidents, runbooks, services, dependencies, health)
- Starts 4 Uvicorn workers on `http://localhost:8000`
- Auto-discovers Docker containers, host processes, and Kubernetes services
- **Note:** `Local embedding model init failed` warning is harmless — app falls back to keyword search

**Verify:** Open `http://localhost:8000/health` → should show `{"status":"ok"}`

---

## Step 3: Start Frontend (Terminal 2)

```powershell
cd "C:\Users\dharm\OneDrive\文档\Worthy One\signalforge_mvp\frontend"

# Install dependencies (one time only)
npm install

# Start dev server
npm run dev
```

**What this does:**
- Installs React 18, TypeScript, Vite, Tailwind CSS, Recharts, Socket.io
- Starts Vite dev server on `http://localhost:5173`
- Hot module replacement: auto-refreshes on code changes
- Connects to backend API at `http://localhost:8000`

**Open:** `http://localhost:5173`

---

## Step 4: Verify Auto-Discovery (Optional)

```bash
curl http://localhost:8000/services/discovered
curl http://localhost:8000/dependencies/graph
```

---

## Stop Everything

- **Backend:** Press `Ctrl+C` in Terminal 1
- **Frontend:** Press `Ctrl+C` in Terminal 2

---

## Common Issues & Fixes

| Issue | Fix |
|-------|-----|
| `table incidents already exists` during migration | `Remove-Item -Force backend/signforge.db` then re-run `alembic upgrade head` |
| `Local embedding model init failed` warning | **Harmless** — app uses keyword search. Or install: `pip install sentence-transformers` |
| Frontend `Expected ")" but found "{"` | Make sure `App.tsx` has `)}` after each tab's closing `</div>` |
| Port 8000 or 5173 in use | Change port: `--port 8001` or `npm run dev -- --port 5174` |
| CORS errors in browser | Backend must run on `0.0.0.0` (not `127.0.0.1`) for browser access |

---

## Full Stack with Docker (One Command)

```bash
cd "C:\Users\dharm\OneDrive\文档\Worthy One\signalforge_mvp\"
docker-compose up -d
```

**What this does:**
- Starts PostgreSQL, Redis, Kafka, Backend, Frontend
- Auto-discovers containers via Docker socket mount
- Access: `http://localhost` (frontend) + `http://localhost:8000` (API)

**Stop:** `docker-compose down`

---

## One-Line Status Check

```bash
curl http://localhost:8000/health
curl http://localhost:8000/services/discovered
curl http://localhost:8000/dependencies/graph
```

All should return JSON. If any fail, check that the backend is running.

---

*SignalForge v0.1.0 — 50 days, 341 tests, 61 modules*
