# Architecture — phase 1

## Free provider routing

`COLA_FREE_ONLY=true` is the default and prevents the application router from
selecting OpenAI, even if an old OpenAI key/provider setting remains. Auto uses
OpenRouter when its dedicated key exists, otherwise Ollama. Offline mode and
prepared-answer priority are preserved. Explicit OpenAI use requires changing
free-only to false; it is never an automatic fallback from OpenRouter.

OpenRouter permits only `:free` model IDs or `openrouter/free`, with zero maximum
prompt, completion and request prices and no paid plugins. The default is
`xingchen-agi/xing4.0-29b-a4b:free`, followed by
`nvidia/nemotron-3.5-super-vl:free`. `COLA_OPENROUTER_FALLBACK_MODELS` is a
comma-separated list validated with the same free-only restriction as the primary.
The ordered, deduplicated list is sent via OpenRouter's `models` parameter;
single-model configurations retain `model`. The existing deadline and zero-price
caps cover the whole request. [Model fallback protocol](https://openrouter.ai/docs/guides/routing/model-fallbacks).
If the free model chain fails, the app falls back to
Ollama, not to its paid variant. Model availability remains external and variable.
The cloud first-text deadline is 12 seconds, including SSE heartbeat time. The
iterator is closed on timeout. Failures after visible text do not switch models.
Structured local guides remain the last fallback when both providers fail.

Speech partials use Ollama only. Final questions may use the cloud. Identical
partial transcripts differing only in whitespace coalesce. OpenRouter requests
have a process-wide four-second minimum interval; excess requests go local
without waiting. HTTP errors put the remote provider into a monotonic cooldown,
with Retry-After honored on 429 (at least 60 seconds). Local counters do not claim
to replace account-wide quotas and reset on process restart. No API key, prompt
or provider error body is logged. The question text and matched local reference
leave the machine when OpenRouter is selected; audio transcription stays local.

References: [provider price limits](https://openrouter.ai/docs/guides/routing/provider-selection#max-price),
[streaming](https://openrouter.ai/docs/api_reference/streaming),
[free model](https://openrouter.ai/nvidia/nemotron-3-nano-30b-a3b:free).

## Hybrid local interview answers

The user authorized persistent interview reference data from their 23,040-row
CSV, covering HR and technology, plus offline answers with an analytical tone.
This is reference-data persistence, not transcript storage or model training.
`scripts.import_interview_bank` atomically builds SQLite with an exact index and
FTS5 candidates. No new dependency is required. The CSV has no answers, so all
imported rows initially carry clearly labeled generic analytical guides. An
authored JSON catalog supplies 12 specific answer bases and aliases. CSV columns
`Resposta` and `Aprovada=sim` allow explicitly authored ready answers on reimport.

Complete ready matches bypass the provider. Others use the configured provider
with matched reference data explicitly distinguished from instructions. Failure
before the first delta falls back to a labeled guide when available; failures
after text has streamed propagate without mixing incompatible responses. Offline
mode never calls a model. Provisional speech does not trigger canned answers.

Retrieval is lexical, not semantic: normalized exact matching first, then FTS
candidates with >=0.90 token Jaccard similarity and a 0.06 ambiguity margin.
Negation and numeric differences reject candidates; C#/C++ retain distinct
tokens. Lookup runs off the event loop. Connections are explicitly closed, which
is necessary for atomic file replacement on Windows. Generated SQLite files are
gitignored; sources and rebuild instructions are versionable. Prepared answers
and generic guides carry different visible labels. HR templates never invent a
candidate's employment history, salary, or measured achievements.

## Editable technical question bank and evaluation

The user authorized a bank of prepared technology questions and real tests.
`tests/technical_cases.json` is the editable evaluation corpus, with unique IDs,
questions, expected behavior and optional source links. It is not model training,
a response cache, or a persistent conversation database. Three short examples in
the shared system prompt demonstrate technical focus, preserving explicit code
identifiers and requesting clarification. The entire corpus is not injected.

`python -m scripts.evaluate_technical` requires an explicit provider and output
path. It validates the corpus before calls, runs sequentially with a per-case
deadline, and saves incremental JSON results including partial output on failure.
Latency uses `time.monotonic()`. Arbitrary exception messages are omitted to avoid
recording credentials. Completion and human quality review are separate fields;
no keyword-based score claims technical correctness. This text-level evaluation
does not validate ASR, audio segmentation or UI behavior. It does not load `.env`
or change app provider selection. No new dependency was added.

## Answer history and faster complete answers (October 2026)

This decision supersedes the replacement-only UI and reasoning-enabled final generation described below. The renderer archives every nonempty answer before displaying a new generation, including provisional or interrupted responses. Cards remain in chronological order, expanded, without forced scrolling. History survives WebSocket reconnection in renderer memory; closing/reloading the app clears it. No transcript persistence or additional model context is introduced. Answer deltas are matched by session, question ID and revision so late output cannot enter another card.

Complete/manual requests now interpret and answer in a single streaming call, using the existing system instructions to ignore unrelated interruptions and ask for clarification. Incomplete speech keeps the structured intent gate to avoid answering before a question exists. Ollama generation uses `think=false`, with 1200 tokens for complete answers and 640 for provisional ones. OpenAI retains its configured model and output limits. This removes one sequential model request from complete answers and removes hidden local reasoning latency, at the cost of relying on one-pass interpretation; technical accuracy must still be evaluated with real questions. No latency guarantee is made. See [OpenAI latency guidance](https://developers.openai.com/api/docs/guides/latency-optimization) on fewer sequential requests and streaming.

First visible delta and completed-answer latency are logged with `time.monotonic_ns()`, without logging question contents or credentials. Audio capture, transcription window size and provider selection are unchanged.

## Authorized extension: local speech-to-answer pipeline

The current implementation extends the original phase below: WASAPI PCM → silence-bounded utterances → faster-whisper CPU/int8 → `transcription.completed` → the existing Ollama streaming answer flow. The user authorized transcription and automatic answers. Recognized text passes through structured question interpretation before answering; conversation persistence is not introduced.

Capture callbacks segment PCM on the audio thread, using a conservative energy threshold and 0.8 seconds of silence, capped at 30 seconds per utterance, with cumulative partial snapshots emitted every 4 seconds even without silence. Whisper's VAD additionally filters nonspeech. WAV containers exist only in memory and preserve source rate/channels for the decoder. A four-item queue drops the oldest pending utterance on overload and emits a visible error. Transcription and answers run in independent async workers per session. Only the answer worker waits for an existing manual answer. Pending snapshots of the same utterance coalesce; only the latest pending answer is retained. Active provisional answers finish before the next revision, avoiding starvation. An obsolete final/reasoning answer is cancelled when a newer transcript arrives. The shared lazy Whisper model lives in a separate local Python worker process, reached over private stdin/stdout JSON-lines pipes. Inference is isolated from the audio reader and asyncio event loop. Requests are serialized; cancellation drains the current response before the next request to prevent stale result delivery. Parent pipe EOF exits the worker; graceful backend shutdown closes it explicitly. Only model weights are cached. Invalid/compressed low-confidence ASR segments are discarded. The model is downloaded once from Hugging Face; audio is processed locally. Model weights are cached, but recordings and transcripts are not persisted.

`transcription.status` reports listening/transcribing/answering/error; `transcription.completed` carries text, sequence and latency measured with `time.monotonic_ns()`. Stopping or disconnecting cancels the pipeline and discards queued/in-flight results. Native inference cannot be interrupted and may finish silently in its worker thread. The UI distinguishes simulation from real answers and resets sequence state on a new session. Electron isolation and narrow preload APIs remain unchanged. The root `.env` is passed to uvicorn when present. HTTPX is now a runtime dependency because the existing Ollama implementation requires it; faster-whisper supplies the authorized local transcription capability.

Limitations: latest utterance only in UI, fixed energy segmentation, no microphone mixing, probabilistic question interpretation, no guaranteed realtime latency. Python 3.12 remains required by the existing audioop-based capture. Ollama/model failures are shown without substituting simulated answers.

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


## Technical understanding and distraction handling

The observed database test failed at two layers: Whisper base corrupted technical names and Llama 3.2 3B elaborated on irrelevant interruptions. Defaults now use Whisper small with beam size 5, zero-temperature decoding and a short technical spelling context, plus Qwen3.5 9B with a scoped technical-assistant system prompt. No keyword substitutions or technology-specific answer templates are used. The displayed transcript remains the ASR output; a separate structured interpretation extracts the main question for the answer model.

Generation uses temperature 0, seed 42, 16384 context tokens and an 8192-token reasoning/response budget, with reasoning enabled to prioritize technical accuracy over latency. This reduces sampling variation but does not guarantee identical or correct answers. The system prompt asks for clarification instead of inventing meanings for unintelligible terms and covers software, databases, networks, cloud, security and AI. A first non-thinking model call returns a Pydantic-validated JSON intent (clear, question, clarification). Unclear input returns a clarification without generating an answer; clear input is passed to a second reasoning-enabled call. The intent stage preserves relevant technical details and literal values while removing unrelated interruptions. This is probabilistic interpretation, not a guarantee of correct question extraction. Both calls use the same context size to avoid reloading the model between stages. Existing environment overrides remain supported. Larger models trade additional download size, memory and latency for quality; validation includes actual local-model and UI capture tests. References: https://ollama.com/library/qwen3.5 and https://github.com/SYSTRAN/faster-whisper.

Reasoning chunks stay in the provider stream and are not shown as answer text. The UI remains in its existing generating state until answer content arrives. Empty or budget-exhausted generations produce an explicit error rather than a false successful completion.

## Continuous speech and provisional answers

The user authorized answering while audio is still arriving. SpeechSnapshot identifies the utterance and whether it is final. The capture thread emits snapshots; ASR publishes transcription.completed with a final flag. Separate answer.activity events track model work without overwriting transcription status. QuestionDetected marks provisional answers. Partial generation uses think=false and 640 tokens; finalized/manual requests use reasoning. An unclear partial produces no answer and waits for more context; an unclear finalized request asks for clarification.

The UI preserves the previous answer until the first replacement delta exists, marks partial text/answers explicitly, and independently displays transcription and response activity. Stop/disconnect cancels both workers and their owned answer task, discards pending work and suppresses late ASR results. Manual requests are not cancelled by stopping capture. Audio/ASR and generation latency are distinct; four-second snapshots do not guarantee a four-second first response. Current audio windows have a 30-second cap. Window boundaries keep the same utterance ID, and up to 6000 characters of prior window text are retained until actual silence. A silent final window can finalize retained text. No context persists across sessions or distinct utterances.

Validation: backend tests cover no-silence snapshots, transcription while a response is blocked, pending revision coalescing, stop/cancellation, continuity across 30-second windows, and subprocess response draining after cancellation. A live UI/WASAPI test emitted its first provisional answer at 15.22 seconds during a 53.82-second synthetic speech playback; subsequent transcription continued while generation was active. This is one-machine evidence, not a latency guarantee. System loopback also captures other programs; background speech/music can contaminate transcription and subsequent answers.

## Authorized extension: OpenAI answer provider and interview persona

The user authorized the OpenAI Chat Completions API as an answer provider because the local 9B model was slow (49–124 s per answer in a live test) and occasionally imprecise. `answer_provider.py` selects the provider via `COLA_LLM_PROVIDER` (`auto` | `ollama` | `openai`); `auto` uses OpenAI only when `OPENAI_API_KEY` is set, otherwise Ollama. Both providers share `answer_system_prompt()` and the same two-stage flow: a structured intent call (OpenAI uses strict `json_schema` output, still validated by Pydantic) followed by a streamed answer. Provider failures derive from `AnswerProviderError` and surface as `session.error` with code `model_unavailable`; no simulated answer is substituted.

The OpenAI client reuses HTTPX (no new dependency) and parses SSE chunks directly. The key is read only from the environment (`.env` is gitignored) and is never logged. Defaults: `gpt-4o-mini`, temperature 0.4 (empty `COLA_OPENAI_TEMPERATURE` omits it for models that reject the parameter), 1200 tokens for final answers and 300 for provisional ones. Privacy trade-off: when OpenAI is selected, the transcribed question text leaves the machine; audio and Whisper transcription remain local.

The system prompt now frames the assistant as supplying the answer an interviewed software engineer would say aloud: first person, conversational, no markdown/lists, ~150 words, code only when indispensable.
