import { describe, expect, it } from "vitest";
import { initialState, reduceEvent } from "./protocol";

describe("reduceEvent", () => {
  it("builds a progressive answer and ignores stale deltas", () => {
    const question = reduceEvent(initialState, { type: "question.detected", version: 1, session_id: "s", question_id: "q", revision: 1, sequence: 1, text: "Pergunta?", simulated: true });
    const firstDelta = reduceEvent(question, { type: "answer.delta", version: 1, session_id: "s", question_id: "q", revision: 1, sequence: 3, delta: "Primeira " });
    const result = reduceEvent(firstDelta, { type: "answer.delta", version: 1, session_id: "s", question_id: "q", revision: 1, sequence: 2, delta: "antiga" });
    expect(result.answer).toBe("Primeira ");
  });
});
