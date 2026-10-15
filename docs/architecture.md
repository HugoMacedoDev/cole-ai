# Architecture — phase 1

```text
React renderer -- WebSocket --> FastAPI session manager --> deterministic simulator
     |                                  |
     +-- narrow IPC/preload --> Electron main process
```

The renderer creates one local WebSocket connection and asks the backend to start a session. FastAPI assigns a server session ID and sends versioned event envelopes. The simulator emits one detected question followed by streamed answer deltas. Every response event contains a session ID, question ID, revision and sequence number where ordering matters.

The Electron renderer has no Node.js access. `contextIsolation` and sandboxing remain enabled. The preload surface is limited to toggling always-on-top and requesting app exit; all model and audio functionality stays out of phase 1.

## Event protocol

Server events use protocol version `1` and types: `session.started`, `question.detected`, `answer.started`, `answer.delta`, `answer.completed`, `answer.cancelled`, and `session.error`. Client commands are deliberately separate and currently only include `session.start` and `answer.cancel`.

## Latency

The simulator delays chunks through `COLA_SIMULATION_DELAY_MS`. Future pipeline measurements must use `time.monotonic_ns()` to avoid wall-clock changes corrupting duration calculations.

