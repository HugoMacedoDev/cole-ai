# Cola AI engineering guide

- Use typed, modular code and keep each function focused on one responsibility.
- Do not add dependencies unless they materially support the current phase.
- Never commit credentials. External calls require an explicit product need.
- Run the relevant tests after changes and report what was actually run.
- Measure latency with monotonic timestamps when adding runtime telemetry.
- Record significant architectural decisions in `docs/architecture.md`.
- Do not implement future phases (audio capture, transcription, model providers, or persistence) without authorization.
- Keep Electron context isolation enabled and expose only narrow, typed preload APIs.

