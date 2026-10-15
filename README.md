# Cola AI

> Inteligência no ritmo da conversa.

Cola AI is an Apache-2.0 licensed Windows desktop assistant. It streams answers from the local Ollama engine without requiring a paid API. The simulation remains available only as a connection diagnostic; audio capture, transcription and persistence are not included yet.

## Requirements

- Node.js 20+ and npm
- Python 3.12+

## Run in development

Initial setup in the repository root:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".\backend[dev]"
npm install
ollama pull llama3.2:3b
```

Run the application with one command:

```powershell
npm run dev:desktop
```

Electron starts the backend from `.venv` automatically. Enter a question and select **Perguntar** to receive streamed local-model output. Copy `.env.example` to `.env` only if you need another model or Ollama address.

## System audio capture (Windows)

Select **Iniciar captura** in the app to capture the current default Windows playback device through WASAPI Loopback (for example, Meet, Teams or WhatsApp Desktop audio). The level meter confirms capture activity and **Parar captura** stops it immediately. Audio is kept in memory only; transcription and automatic question detection are not enabled yet.

## Test

```powershell
.\.venv\Scripts\python.exe -m pytest
npm test
```

## Project layout

- `desktop/` — Electron main/preload plus React renderer.
- `backend/` — local FastAPI server and typed WebSocket event contracts.
- `tests/` — Python backend tests.
- `docs/` — architecture and roadmap.

See [architecture](docs/architecture.md) and [roadmap](docs/roadmap.md) for technical decisions and scope.

