export type ConnectionStatus = "connecting" | "connected" | "disconnected";

export type ServerEvent =
  | { type: "session.started"; session_id: string; version: 1 }
  | { type: "question.detected"; session_id: string; question_id: string; revision: number; sequence: number; text: string; simulated: boolean; version: 1 }
  | { type: "answer.started"; session_id: string; question_id: string; revision: number; sequence: number; version: 1 }
  | { type: "answer.delta"; session_id: string; question_id: string; revision: number; sequence: number; delta: string; version: 1 }
  | { type: "answer.completed"; session_id: string; question_id: string; revision: number; sequence: number; version: 1 }
  | { type: "answer.cancelled"; session_id: string; question_id: string; revision: number; sequence: number; version: 1 }
  | { type: "session.error"; session_id: string; code: string; message: string; version: 1 }
  | { type: "audio.capture.started"; session_id: string; version: 1 }
  | { type: "audio.capture.stopped"; session_id: string; version: 1 }
  | { type: "audio.level"; session_id: string; sequence: number; level: number; version: 1 };

export interface UiState {
  connection: ConnectionStatus;
  question: string;
  answer: string;
  isStreaming: boolean;
  lastSequence: number;
  sessionId?: string;
  captureActive: boolean;
  audioLevel: number;
  error?: string;
}

export const initialState: UiState = {
  captureActive: false,
  audioLevel: 0,
  connection: "connecting", question: "Aguardando pergunta simulada…", answer: "", isStreaming: false, lastSequence: 0,
};

export function reduceEvent(state: UiState, event: ServerEvent): UiState {
  const sequence = "sequence" in event ? event.sequence : state.lastSequence;
  if ("sequence" in event && event.sequence <= state.lastSequence) return state;
  switch (event.type) {
    case "session.started":
      return { ...state, sessionId: event.session_id };
    case "audio.capture.started":
      return { ...state, captureActive: true, error: undefined };
    case "audio.capture.stopped":
      return { ...state, captureActive: false, audioLevel: 0 };
    case "audio.level":
      return { ...state, audioLevel: event.level, lastSequence: sequence };
    case "question.detected":
      return { ...state, question: event.text, answer: "", isStreaming: false, lastSequence: sequence, error: undefined };
    case "answer.started":
      return { ...state, isStreaming: true, lastSequence: sequence };
    case "answer.delta":
      return { ...state, answer: state.answer + event.delta, lastSequence: sequence };
    case "answer.completed":
    case "answer.cancelled":
      return { ...state, isStreaming: false, lastSequence: sequence };
    case "session.error":
      return { ...state, isStreaming: false, error: event.message };
    default:
      return state;
  }
}
