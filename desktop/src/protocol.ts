export type ConnectionStatus = "connecting" | "connected" | "disconnected";

export type ServerEvent =
  | { type: "answer.activity"; session_id: string; active: boolean; provisional: boolean; version: 1 }
  | { type: "transcription.status"; session_id: string; status: TranscriptionStatus; version: 1 }
  | { type: "transcription.completed"; session_id: string; sequence: number; text: string; latency_ms: number; final?: boolean; version: 1 }
  | { type: "session.started"; session_id: string; version: 1 }
  | { type: "question.detected"; session_id: string; question_id: string; revision: number; sequence: number; text: string; simulated: boolean; provisional?: boolean; version: 1 }
  | { type: "answer.started"; session_id: string; question_id: string; revision: number; sequence: number; version: 1 }
  | { type: "answer.delta"; session_id: string; question_id: string; revision: number; sequence: number; delta: string; version: 1 }
  | { type: "answer.completed"; session_id: string; question_id: string; revision: number; sequence: number; version: 1 }
  | { type: "answer.cancelled"; session_id: string; question_id: string; revision: number; sequence: number; version: 1 }
  | { type: "session.error"; session_id: string; code: string; message: string; version: 1 }
  | { type: "audio.capture.started"; session_id: string; version: 1 }
  | { type: "audio.capture.stopped"; session_id: string; version: 1 }
  | { type: "audio.level"; session_id: string; sequence: number; level: number; version: 1 };

export type TranscriptionStatus = "idle" | "listening" | "transcribing" | "answering" | "error";

export interface AnswerRecord {
  id: string;
  question: string;
  answer: string;
  provisional: boolean;
  incomplete: boolean;
  simulated: boolean;
}

export interface UiState {
  history: AnswerRecord[];
  questionId?: string;
  revision?: number;
  answerComplete: boolean;
  answerPending: boolean;
  provisionalAnswer: boolean;
  transcriptFinal: boolean;
  transcript: string;
  transcriptionStatus: TranscriptionStatus;
  simulated: boolean;
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
  history: [],
  answerComplete: false,
  answerPending: false,
  provisionalAnswer: false,
  transcriptFinal: true,
  transcript: "",
  transcriptionStatus: "idle",
  simulated: false,
  captureActive: false,
  audioLevel: 0,
  connection: "connecting", question: "Aguardando pergunta ou transcrição…", answer: "", isStreaming: false, lastSequence: 0,
};

function archiveAnswer(state: UiState): AnswerRecord[] {
  if (!state.answer) return state.history;
  return [...state.history, {
    id: `${state.sessionId}:${state.questionId}:${state.revision}:${state.lastSequence}`,
    question: state.question, answer: state.answer,
    provisional: state.provisionalAnswer, incomplete: !state.answerComplete,
    simulated: state.simulated,
  }];
}

export function reduceEvent(state: UiState, event: ServerEvent): UiState {
  if (event.type !== "session.started" && state.sessionId && event.session_id !== state.sessionId) return state;
  const sequence = "sequence" in event ? event.sequence : state.lastSequence;
  if ("sequence" in event && event.sequence <= state.lastSequence) return state;
  if (event.type.startsWith("answer.") && "question_id" in event &&
      (event.question_id !== state.questionId || event.revision !== state.revision)) return state;
  switch (event.type) {
    case "session.started":
      return { ...initialState, history: archiveAnswer(state), connection: state.connection, sessionId: event.session_id };
    case "transcription.status":
      return { ...state, transcriptionStatus: event.status };
    case "answer.activity":
      return { ...state, answerPending: event.active, isStreaming: event.active ? state.isStreaming : false };
    case "transcription.completed":
      return { ...state, transcript: event.text, transcriptFinal: event.final ?? true, lastSequence: sequence, error: undefined };
    case "audio.capture.started":
      return { ...state, captureActive: true, transcriptionStatus: "listening", error: undefined };
    case "audio.capture.stopped":
      return { ...state, captureActive: false, audioLevel: 0, transcriptionStatus: "idle", isStreaming: false, answerPending: false };
    case "audio.level":
      return { ...state, audioLevel: event.level, lastSequence: sequence };
    case "question.detected":
      return { ...state, history: archiveAnswer(state), questionId: event.question_id, revision: event.revision, answerComplete: false, question: event.text, simulated: event.simulated, provisionalAnswer: event.provisional ?? false, answer: "", isStreaming: false, lastSequence: sequence, error: undefined };
    case "answer.started":
      return { ...state, isStreaming: true, lastSequence: sequence };
    case "answer.delta":
      return { ...state, answer: state.answer + event.delta, lastSequence: sequence };
    case "answer.completed":
      return { ...state, answerComplete: true, isStreaming: false, lastSequence: sequence };
    case "answer.cancelled":
      return { ...state, isStreaming: false, lastSequence: sequence };
    case "session.error":
      return { ...state, isStreaming: false, error: event.message };
    default:
      return state;
  }
}
