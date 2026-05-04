# AI Lab GUI — Phase 1 (Audit-Aligned)

Thin-client desktop app for the MutesHand AI Lab system.

## Architecture

```
User → React UI → FastAPI → orchestrator_runtime.execute_from_input
                           → user_control (pause/resume/override)
                           → BackgroundManager
                           → user_approval
                           → system_entry  ← sole execution path
```

**The UI contains zero logic. The API contains zero decision logic.**
All execution flows through `orchestrator → system_entry`.

---

## Project Structure

```
ai_lab_gui/
├── backend/
│   ├── api.py           ← FastAPI, wired to real system contracts
│   └── requirements.txt
├── frontend/
│   ├── index.html
│   ├── vite.config.js
│   ├── package.json
│   └── src/
│       ├── main.jsx
│       ├── App.jsx
│       ├── api.js       ← fetch wrapper, no logic
│       ├── styles.css
│       └── components/
│           ├── ChatPanel.jsx       ← input → POST /execute
│           ├── WorkflowPanel.jsx   ← displays trace steps + status
│           ├── ExecutionPanel.jsx  ← displays execution_result JSON
│           ├── ControlPanel.jsx    ← pause/resume/override/bg start
│           ├── BackgroundPanel.jsx ← bg workflow list + status
│           └── ApprovalPanel.jsx   ← conditional approve/deny (governance-gated)
└── src-tauri/
    ├── tauri.conf.json
    ├── Cargo.toml
    ├── build.rs
    └── src/
        ├── main.rs
        └── lib.rs
```

---

## Startup (Auto)

When launched as a Tauri `.exe`, the backend starts automatically — no manual steps required.

Startup sequence:
1. Tauri app launches → `lib.rs` spawns `python -m uvicorn ai_lab_gui.backend.api:app --port 8000`
2. React UI polls `GET /status` up to 20× at 500ms intervals
3. On success → UI renders normally
4. On timeout → UI shows error screen with Retry button

---

## Run (Development)

### 1 — Backend (manual, for dev only)

```powershell
# From repo root (e:\MutesHand)
cd ai_lab_gui\backend
pip install -r requirements.txt
uvicorn api:app --reload --port 8000
```

### 2 — Frontend dev server

```powershell
cd ai_lab_gui\frontend
npm install
npm run dev
# Opens at http://localhost:5173
# api.js uses http://localhost:8000 directly — backend must be running
```

### 3 — Tauri desktop (dev)

Requires Rust + Tauri CLI:

```powershell
cargo install tauri-cli
cd ai_lab_gui\frontend
npm run tauri dev
# Tauri auto-starts backend via lib.rs start_backend()
```

---

## Build .exe

```powershell
cd ai_lab_gui\frontend
npm run tauri build
# Output: src-tauri/target/release/bundle/
```

> The backend (FastAPI/uvicorn) must be running locally for the desktop app to function.
> Bundle it with the `.exe` using a sidecar or start it as a subprocess via Tauri shell plugin.

---

## API Endpoints

| Method | Path | Calls |
|--------|------|-------|
| POST | `/execute` | `orchestrator_runtime.execute_from_input(input)` |
| POST | `/pause` | `user_control.pause()` |
| POST | `/resume` | `user_control.resume()` |
| POST | `/override` | `user_control.set_override(value)` |
| GET  | `/status` | `user_control.get_control_state()` |
| POST | `/background/start` | `background_manager.start_workflow()` |
| GET  | `/background/list` | `background_manager.list_workflows()` |
| GET  | `/background/status/{id}` | `background_manager.get_status(id)` |
| GET  | `/approval/pending` | returns pending approval queue |
| POST | `/approve` | resolves governance-blocked step (approve) |
| POST | `/deny` | resolves governance-blocked step (deny) |

---

## Hard Prohibitions (enforced)

- No `main.py` calls anywhere in this project
- No execution logic in UI or API
- No modification of `execution_result`
- No bypass of governance
- No planner UI / retry UI / cancel UI
