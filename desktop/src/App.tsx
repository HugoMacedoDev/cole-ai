import { AudioLines, BrainCircuit, Settings2, Power, Wifi, WifiOff, X, Send, Play, Mic, Square } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { initialState, reduceEvent, type ConnectionStatus, type ServerEvent, type UiState } from "./protocol";
import "./styles.css";

const url = import.meta.env.VITE_COLA_WS_URL ?? "ws://127.0.0.1:8000/ws";

function useColaSocket(): UiState & { ask: (question: string) => void; simulate: () => void; toggleCapture: (active: boolean) => void } {
  const [state, setState] = useState<UiState>(initialState);
  const retry = useRef(0);
  const socketReference = useRef<WebSocket>();
  useEffect(() => {
    let socket: WebSocket | undefined;
    let reconnectTimer: number | undefined;
    let closed = false;
    const connect = () => {
      setState((current) => ({ ...current, connection: "connecting" }));
      socket = new WebSocket(url);
      socketReference.current = socket;
      socket.onopen = () => {
        retry.current = 0;
        setState((current) => ({ ...current, connection: "connected", error: undefined }));
        socket?.send(JSON.stringify({ type: "session.start" }));
      };
      socket.onmessage = (message) => {
        try { setState((current) => reduceEvent(current, JSON.parse(message.data) as ServerEvent)); }
        catch { setState((current) => ({ ...current, error: "Evento inválido recebido do backend." })); }
      };
      socket.onerror = () => socket?.close();
      socket.onclose = () => {
        if (closed) return;
        setState((current) => ({ ...current, connection: "disconnected", captureActive: false, audioLevel: 0, transcriptionStatus: "idle", isStreaming: false, answerPending: false }));
        const delay = Math.min(1_000 * 2 ** retry.current++, 10_000);
        reconnectTimer = window.setTimeout(connect, delay);
      };
    };
    connect();
    return () => { closed = true; if (reconnectTimer) window.clearTimeout(reconnectTimer); socket?.close(); };
  }, []);
  const send = (message: object) => {
    if (socketReference.current?.readyState === WebSocket.OPEN) socketReference.current.send(JSON.stringify(message));
  };
  return {
    ...state,
    ask: (question) => send({ type: "question.ask", text: question }),
    simulate: () => send({ type: "simulation.start" }),
    toggleCapture: (active) => send({ type: active ? "audio.capture.stop" : "audio.capture.start" }),
  };
}

function Status({ status }: { status: ConnectionStatus }): JSX.Element {
  const online = status === "connected";
  return <span className={`status ${status}`}>{online ? <Wifi size={14} /> : <WifiOff size={14} />}{online ? "Backend conectado" : status === "connecting" ? "Conectando…" : "Reconectando…"}</span>;
}

export default function App(): JSX.Element {
  const state = useColaSocket();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [alwaysOnTop, setAlwaysOnTop] = useState(false);
  const [draftQuestion, setDraftQuestion] = useState("Como você faria uma migração de banco de dados sem interromper a aplicação?");
  const changeAlwaysOnTop = async (enabled: boolean) => {
    setAlwaysOnTop(enabled);
    await window.cola?.desktop.setAlwaysOnTop(enabled);
  };
  return <main className="app-shell">
    <header>
      <div className="brand"><div className="brand-icon"><BrainCircuit size={31} /></div><div><h1>Cola <em>AI</em></h1><p>Inteligência no ritmo da conversa.</p></div></div>
      <div className="actions"><Status status={state.connection} /><button className="icon-button" aria-label="Configurações" onClick={() => setSettingsOpen(true)}><Settings2 size={19} /></button><button className="icon-button danger" aria-label="Encerrar aplicativo" onClick={() => void window.cola?.desktop.quit()}><Power size={18} /></button></div>
    </header>
    <div className="divider" />
    <section className="badges"><span>Open source</span><span>Windows</span><span>Local + Nuvem</span><span>Tempo real</span><span className={`audio ${state.captureActive ? "capturing" : ""}`}><AudioLines size={14} /> {state.captureActive ? "Captura ativa" : "Captura inativa"}</span></section>
    <section className="capture-panel"><div><strong>Áudio da reunião</strong><p>{state.captureActive ? "Transcrição e resposta automáticas do áudio do Windows." : "Use WASAPI Loopback para captar o áudio reproduzido no computador."}</p></div><div className="capture-controls"><div className="level-meter" aria-label="Nível de áudio"><i style={{ transform: `scaleX(${Math.max(0.03, state.audioLevel)})` }} /></div><button className={`capture-button ${state.captureActive ? "active" : ""}`} disabled={state.connection !== "connected"} onClick={() => state.toggleCapture(state.captureActive)}>{state.captureActive ? <Square size={15} /> : <Mic size={16} />}{state.captureActive ? "Parar captura" : "Iniciar captura"}</button></div></section>
    <section className="transcript-panel" aria-live="polite"><div className="section-label"><span>TRANSCRIÇÃO {state.transcript && !state.transcriptFinal && "(PARCIAL)"}</span><small>{{ idle: "Parada", listening: "Ouvindo", transcribing: "Transcrevendo…", answering: "Gerando resposta…", error: "Falha na transcrição" }[state.transcriptionStatus]}</small></div><p>{state.transcript || "Inicie a captura. O texto aparece e se atualiza enquanto você fala."}</p></section>
    {state.history.length > 0 && <section className="answer-history" aria-label="Respostas anteriores">
      <div className="section-label"><span>RESPOSTAS ANTERIORES ({state.history.length})</span></div>
      {state.history.map((entry) => <article className="answer-card" key={entry.id}>
        <div className="section-label"><span>PERGUNTA</span><small>{entry.simulated ? "SIMULAÇÃO" : entry.incomplete ? "INTERROMPIDA" : entry.provisional ? "PARCIAL" : "RESPOSTA"}</small></div>
        <p className="question">{entry.question}</p>
        <div className="divider internal" />
        <p className="answer">{entry.answer}</p>
      </article>)}
    </section>}
    <section className="answer-card" aria-live="polite">
      <div className="section-label"><span>PERGUNTA IDENTIFICADA</span><AudioLines size={19} /></div>
      <p className="question">{state.question}</p>
      <div className="divider internal" />
      <div className="section-label"><span>RESPOSTA SUGERIDA</span><small>{state.simulated ? "SIMULAÇÃO" : state.provisionalAnswer ? "PARCIAL" : "IA"}</small></div>
      <p className="answer">{state.answer || (state.isStreaming || state.answerPending ? "Gerando resposta…" : "Aguardando uma pergunta ou fala transcrita.")}{state.isStreaming && <i className="cursor" />}</p>
      {state.answerPending && !state.isStreaming && <p className="answer-progress" role="status">Preparando resposta com o contexto recebido… {state.captureActive && "Continuo ouvindo."}</p>}
      {state.error && <p className="error">{state.error}</p>}
    </section>
    <section className="ask-panel" aria-label="Perguntar à inteligência artificial local">
      <label htmlFor="question-input">Pergunte à IA ou à base de entrevistas</label>
      <div className="ask-row"><input id="question-input" value={draftQuestion} onChange={(event) => setDraftQuestion(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") state.ask(draftQuestion); }} /><button className="primary-button" disabled={state.connection !== "connected" || state.isStreaming || state.answerPending || !draftQuestion.trim()} onClick={() => state.ask(draftQuestion)}><Send size={16} /> Perguntar</button></div>
      <button className="simulation-button" disabled={state.connection !== "connected" || state.isStreaming || state.answerPending} onClick={state.simulate}><Play size={14} /> Testar simulação</button>
    </section>
    {settingsOpen && <div className="modal-overlay" role="presentation"><section className="modal" role="dialog" aria-modal="true" aria-labelledby="settings-title"><div className="modal-title"><h2 id="settings-title">Configurações básicas</h2><button className="icon-button" aria-label="Fechar" onClick={() => setSettingsOpen(false)}><X size={18} /></button></div><label className="toggle"><span>Manter janela sempre visível</span><input type="checkbox" checked={alwaysOnTop} onChange={(event) => void changeAlwaysOnTop(event.target.checked)} /></label><p>Transcrição local em português e respostas pelo Ollama. A captura inclui o som reproduzido pelo computador.</p></section></div>}
  </main>;
}
