# Cola AI

> Inteligência no ritmo da conversa.

Cola AI is an Apache-2.0 licensed Windows desktop assistant. It captures Windows playback audio, transcribes speech locally and streams answers from Ollama without a paid API. Simulation remains available as a connection diagnostic. Recordings and transcripts are not persisted.

## Requirements

- Node.js 20+ and npm
- Python 3.12

## Run in development

Initial setup in the repository root:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".\backend[dev]"
npm install
ollama pull qwen3.5:9b
```

Run the application with one command:

```powershell
npm run dev:desktop
```

Electron starts the backend from `.venv` automatically. Enter a question and select **Perguntar** to receive streamed local-model output. Copy `.env.example` to `.env` only if you need another model or Ollama address.

## System audio capture (Windows)

Select **Iniciar captura** to capture the default Windows playback device through WASAPI Loopback (for example, Meet, Teams or WhatsApp Desktop audio). While speech continues, cumulative audio snapshots are submitted every 4 seconds for local Portuguese transcription. Once the main question is understandable, a provisional answer streams without waiting for silence. A pause of about 0.8 seconds finalizes the utterance and requests a more detailed revision. Continuous speech uses 30-second audio windows, retaining up to 6000 characters of context across windows of the same uninterrupted utterance. A real pause starts a new utterance; there is no persistent conversation memory. The microphone is not included unless Windows plays it through the captured output.

The **Transcrição** panel shows the latest recognized utterance and processing status. The first use downloads the Whisper `small` model; subsequent uses reuse its local cache. Audio stays in memory and is not uploaded or saved. Processing speed depends on CPU and model size. **Parar captura** discards pending audio and cancels the automatic answer; an already running native transcription finishes in the background with its result discarded. Transcription runs in a separate local process so native inference does not block the audio reader. Transcription and answer generation run independently. Repeated snapshots of one utterance replace older pending snapshots, and only the newest pending answer is retained. Up to four different audio windows are queued; overload produces a visible warning. Partial text and answers are labeled PARCIAL. The previous answer stays visible until replacement text arrives. Actual response latency depends on hardware, model loading and whether enough of the question has been spoken.

Use Python 3.12 for the current WASAPI implementation (`audioop` is unavailable in Python 3.13). Install dependencies with `pip install -e ".\\backend[dev]"`. Install and start Ollama, then run `ollama pull qwen3.5:9b`. Without Ollama, transcription still appears, with an actionable error for the answer. Optional `.env` settings: `COLA_WHISPER_MODEL=small`, `COLA_TRANSCRIPTION_LANGUAGE=pt`, and `COLA_OLLAMA_MODEL=qwen3.5:9b`. Electron loads the root `.env` when starting the backend.

## Base de entrevistas (RH e tecnologia)

### APIs gratuitas e fallback local

O aplicativo usa `COLA_FREE_ONLY=true` por padrão. Respostas prontas vêm primeiro;
perguntas finais podem ir ao OpenRouter e, se ele falhar antes do primeiro texto,
ao Ollama. Falas parciais usam apenas Ollama para economizar a cota gratuita.

No `.env`, configure sua chave (não a envie no chat):

```dotenv
COLA_LLM_PROVIDER=auto
COLA_FREE_ONLY=true
OPENROUTER_API_KEY=sua_chave
COLA_OPENROUTER_MODEL=xingchen-agi/xing4.0-29b-a4b:free
COLA_OPENROUTER_FALLBACK_MODELS=nvidia/nemotron-3.5-super-vl:free
```

Crie a chave nas [configurações do OpenRouter](https://openrouter.ai/settings/keys)
e salve o `.env`. A ordem configurada é Xing 4.0, Nemotron 3.5 Super VL e, se
ambos falharem, Ollama. O OpenRouter recebe a lista de modelos em ordem numa
única requisição. Esses modelos são remotos: não há download de pesos local.
Uma única chave OpenRouter atende ambos. Depois de configurar a chave,
reinicie o backend. Sem essa chave, o aplicativo usa Ollama. A integração aceita
somente modelos `:free` ou `openrouter/free`, limita preços a zero e nunca usa um
modelo pago como fallback. A oferta gratuita pode mudar; `openrouter/free` é uma
alternativa que escolhe dentre os modelos gratuitos disponíveis. A precisão e a
latência de cada modelo precisam ser avaliadas; a integração não as garante.

O texto das perguntas e a referência local correspondente são enviados ao
OpenRouter quando ele é selecionado. O áudio continua sendo transcrito localmente.
Ollama precisa estar em execução para gerar respostas locais novas; sem ambos os
provedores, permanecem disponíveis as respostas prontas e roteiros identificados.

### Importar perguntas

O arquivo `perguntas_entrevista_ti_mais_20mil.csv` pode ser importado com
`.\.venv\Scripts\python.exe -m scripts.import_interview_bank`. A base local
responde perguntas preparadas sem IA e oferece roteiros identificados para
perguntas ainda sem resposta específica. Veja [cobertura, edição de respostas e
modo offline](docs/interview-bank.md). O banco de perguntas não treina o modelo.

## Test

### Banco de perguntas técnicas

Edite `tests/technical_cases.json` para adicionar perguntas (`name`, `question`,
`expected_behavior` e, opcionalmente, `sources`). Há 12 casos iniciais, incluindo
C#, .NET, EF Core, PostgreSQL, Redis, redes, testes, interrupções aleatórias e
perguntas incompletas. Cada caso descreve o que revisar na resposta.

Execute o banco real no modelo local, sem alterar o provedor do aplicativo:

```powershell
.\.venv\Scripts\python.exe -m scripts.evaluate_technical --provider ollama --output docs/technical-evaluation.json
```

Para selecionar perguntas, acrescente `--case csharp_async --case ef_tracking`.
O relatório registra resposta, erros, tempo até o primeiro trecho e tempo total.
`completed` significa somente que a geração terminou: a qualidade fica pendente
de revisão. Esses testes usam texto diretamente; não validam reconhecimento de
voz nem a interface. O comando não roda automaticamente no pytest e não carrega
`.env`. Para OpenAI, escolha explicitamente `--provider openai` com as variáveis
de ambiente já configuradas; as chamadas usam a API e podem gerar custos.

O banco é um conjunto de avaliação editável, não treinamento ou respostas fixas.
As instruções compartilhadas da IA incluem três exemplos curtos de foco técnico;
o banco inteiro não é enviado a cada pergunta para evitar aumentar a latência.

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


## Technical-answer quality

The default local answer model is Qwen3.5 9B. Generation uses temperature 0 and a fixed seed to reduce variation, with extended reasoning disabled and a 1200-token limit for complete answers. Complete questions use one streamed call; live partial answers retain an intent check and a 640-token response limit. The system instructions ask the assistant to focus on the principal question, ignore unrelated interruptions and request clarification when the transcript cannot support a reliable answer. It does not browse documentation or guarantee correct answers across all technologies. Prepared questions make regressions visible; they do not ensure that generated code is correct.

Whisper small uses beam search and technical spelling context; raw recognized text is still shown without hard-coded term replacements. The larger models require more memory and may increase latency. Existing environment overrides take precedence. Answers preserve line breaks for readable code examples.
