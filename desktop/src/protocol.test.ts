import { describe, expect, it } from "vitest";
import { initialState, reduceEvent, type UiState } from "./protocol";

function question(state: UiState, id: string, sequence: number, provisional = false): UiState {
  return reduceEvent(state, { type: "question.detected", version: 1, session_id: "s", question_id: id, revision: 1, sequence, text: id, simulated: false, provisional });
}

function delta(state: UiState, id: string, sequence: number, text: string): UiState {
  return reduceEvent(state, { type: "answer.delta", version: 1, session_id: "s", question_id: id, revision: 1, sequence, delta: text });
}

describe("reduceEvent", () => {
  it("preserves earlier cards while subsequent answers stream", () => {
    let state = question(initialState, "C#", 1);
    state = delta(state, "C#", 2, "Resposta C#");
    state = reduceEvent(state, { type: "answer.completed", version: 1, session_id: "s", question_id: "C#", revision: 1, sequence: 3 });
    state = question(state, ".NET", 4, true);
    state = delta(state, ".NET", 5, "Resposta parcial");
    state = question(state, "EF Core", 6);
    state = delta(state, "EF Core", 7, "Nova resposta");
    expect(state.history.map((entry) => entry.answer)).toEqual(["Resposta C#", "Resposta parcial"]);
    expect(state.history.map((entry) => entry.incomplete)).toEqual([false, true]);
    expect(state.answer).toBe("Nova resposta");
    // A late chunk from a previous question must not contaminate the current card.
    expect(delta(state, ".NET", 8, "atrasada")).toBe(state);
  });
  it("retains answers on errors and reconnect without archiving blank cards", () => {
    let state = question(initialState, "q", 1);
    state = delta(state, "q", 2, "Já disponível");
    state = reduceEvent(state, { type: "session.error", session_id: "s", version: 1, code: "model", message: "Falha" });
    expect(state.answer).toBe("Já disponível");
    state = reduceEvent(state, { type: "session.started", session_id: "new", version: 1 });
    expect(state.history[0].answer).toBe("Já disponível");
    expect(delta(state, "q", 100, "sessão antiga")).toBe(state);
    state = reduceEvent(state, { type: "session.started", session_id: "newer", version: 1 });
    expect(state.history).toHaveLength(1);
  });
  it("updates partial transcription without interrupting an answer", () => {
    const state = reduceEvent({ ...initialState, answer: "Em andamento", isStreaming: true }, { type: "transcription.completed", session_id: "s", sequence: 1, text: "Mais contexto", latency_ms: 50, final: false, version: 1 });
    expect(state.answer).toBe("Em andamento");
    expect(state.isStreaming).toBe(true);
    expect(state.transcriptFinal).toBe(false);
    const preparing = reduceEvent(state, { type: "answer.activity", active: true, provisional: true, version: 1, session_id: "s" });
    expect(preparing.answerPending).toBe(true);
    expect(preparing.answer).toBe("Em andamento");
  });
  it("shows transcription independently of the current answer and resets on reconnect", () => {
    const state = reduceEvent({ ...initialState, answer: "Anterior", lastSequence: 4 }, { type: "transcription.completed", version: 1, session_id: "s", sequence: 5, text: "Fala reconhecida", latency_ms: 250 });
    expect(state.transcript).toBe("Fala reconhecida");
    expect(state.answer).toBe("Anterior");
    const reconnected = reduceEvent(state, { type: "session.started", version: 1, session_id: "new" });
    expect(reconnected.lastSequence).toBe(0);
    expect(reconnected.captureActive).toBe(false);
  });
  it("clears processing state when capture stops", () => {
    const state = reduceEvent({ ...initialState, captureActive: true, transcriptionStatus: "transcribing", audioLevel: 0.5 }, { type: "audio.capture.stopped", version: 1, session_id: "s" });
    expect(state.transcriptionStatus).toBe("idle");
    expect(state.audioLevel).toBe(0);
  });
  it("builds a progressive answer and ignores stale deltas", () => {
    const question = reduceEvent(initialState, { type: "question.detected", version: 1, session_id: "s", question_id: "q", revision: 1, sequence: 1, text: "Pergunta?", simulated: true });
    const firstDelta = reduceEvent(question, { type: "answer.delta", version: 1, session_id: "s", question_id: "q", revision: 1, sequence: 3, delta: "Primeira " });
    const result = reduceEvent(firstDelta, { type: "answer.delta", version: 1, session_id: "s", question_id: "q", revision: 1, sequence: 2, delta: "antiga" });
    expect(result.answer).toBe("Primeira ");
  });
});
