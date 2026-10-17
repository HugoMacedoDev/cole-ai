# Base híbrida de entrevistas

O CSV original tem 23.040 perguntas, 16 categorias e nenhuma coluna de respostas.
A importação preserva o original e cria `data/interview.sqlite`, um índice SQLite
local reconstruível. Não treina pesos de um modelo nem salva conversas.

## Comportamento

1. Uma pergunta completa que corresponda a uma resposta preparada recebe a
   resposta local imediatamente, sem chamada ao modelo.
2. Para as outras perguntas, a IA continua disponível. Quando encontra uma
   referência próxima, recebe categoria, tema e o roteiro, identificado como
   material genérico, para ajudar na resposta.
3. Se a IA falhar antes de produzir texto, uma correspondência local permite
   mostrar o roteiro. A interface identifica **IA indisponível** e **Roteiro
   local — ainda sem resposta específica**. Isso não resolve a dúvida técnica
   quando falta conteúdo; orienta como estruturar a resposta.
4. Sem correspondência confiável, o sistema não escolhe um tema aleatório.
   Em modo offline, pede para informar o tema e reformular a pergunta.

A primeira versão contém **12 respostas-base preparadas**, com várias perguntas
equivalentes, em `backend/app/interview_answers.json`: apresentação, pontos
fortes, melhoria, conflitos, pressão, motivação, salário, erro em projeto,
async/await, DI, AsNoTracking e .Result. Os exemplos pessoais devem ser adaptados
à experiência verdadeira do candidato. A pretensão salarial usa um campo para
preencher, não um valor inventado. Não há 23.040 respostas específicas prontas:
as linhas sem resposta aprovada recebem apenas um roteiro analítico.

A busca reconhece texto normalizado e variações muito próximas, com aliases
explícitos para perguntas frequentes. Não é busca semântica por embeddings.
Negações, números e diferença entre C, C# e C++ são preservados. Perguntas
compostas e correspondências ambíguas são tratadas conservadoramente. Respostas
prontas não são disparadas por falas parciais, que ainda podem mudar de sentido.

## Importar e atualizar

```powershell
.\.venv\Scripts\python.exe -m scripts.import_interview_bank
```

Para fornecer respostas específicas no próprio CSV, adicione as colunas
`Resposta` e `Aprovada`. Use `Aprovada=sim` somente nas respostas que deseja
disponibilizar diretamente. Respostas sem esse campo ficam fora das respostas
prontas. Também é possível editar o catálogo JSON para adicionar perguntas
equivalentes e respostas-base. Reexecute a importação depois de editar.

```powershell
.\.venv\Scripts\python.exe -m scripts.import_interview_bank --csv meu_banco.csv --output data/interview.sqlite
```

A importação constrói um arquivo temporário e substitui o banco somente após
validar os dados. Não modifica o CSV. O banco gerado é ignorado pelo Git; o CSV
e o catálogo são as fontes. Em outra máquina, execute a importação novamente.

## Usar sem modelo

Defina `COLA_LLM_PROVIDER=offline` no `.env` e reinicie o backend. Isso desativa
chamadas de geração; as respostas preparadas e roteiros continuam disponíveis.
Nos modos `auto`, `openrouter` ou `ollama`, a base pronta é consultada primeiro e o
modelo atende o restante. A configuração gratuita agora usa OpenRouter quando há
chave e Ollama como alternativa. OpenAI só é selecionada com `COLA_FREE_ONLY=false`;
o modo gratuito não consome créditos da OpenAI.

Perguntas do CSV, como “rollback de motivação para a vaga”, resultam de combinações
de modelos de perguntas com temas. Devem ser reescritas para entrevistas reais.
Volume de perguntas não substitui qualidade de perguntas e respostas.

## Validação executada

A importação registrou 23.040 linhas e 12 respostas-base com 28 formulações
prontas, totalizando 23.068 registros. Duplicatas de texto são permitidas quando
a resposta é consistente; respostas conflitantes do mesmo nível são recusadas.

Na janela Electron real, uma pergunta sobre AsNoTracking foi respondida pela
base em aproximadamente 0,11 s; uma pergunta de RH preparada também em 0,11 s.
Uma pergunta do CSV ainda sem resposta específica retornou o roteiro identificado
após a indisponibilidade da IA, em 1,17 s. Os cartões anteriores permaneceram no
histórico. Tempos incluem a consulta da interface a cada 100 ms; são uma amostra,
não uma garantia. Veja [registro da execução](interview-live-validation.json).

Os testes automatizados cobrem ausência de chamadas ao modelo para respostas
prontas, modo offline, fallback, correspondências incorretas, conflitos e falha
depois do início de uma resposta. Nenhum teste afirma que todos os temas do CSV
possuem resposta factual completa.
