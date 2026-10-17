# Avaliação do banco de perguntas técnicas

Execução local em 17/10/2026, Ollama com Qwen3.5:9b, sem raciocínio prolongado.
Foram enviadas as 12 perguntas de `tests/technical_cases.json`, em sequência,
diretamente ao provedor, com os exemplos curtos de foco técnico no prompt.
As respostas integrais e tempos estão em [technical-evaluation.json](technical-evaluation.json).
Não houve captura de áudio, teste da interface ou chamada OpenAI nesta rodada.

## Funcionamento e velocidade

- 12/12 gerações concluídas, sem erros de transporte ou timeout.
- Primeiro trecho: 0,45 a 0,66 s; resposta completa: 2,17 a 7,95 s.
- Modelo já carregado localmente. Uma rodada não representa latência com modelo
  frio, ASR, API remota ou hardware diferente. Não atribuir a melhora ao banco:
  não foi feito um experimento controlado antes/depois dos exemplos.
- 39 testes automatizados do backend passaram, incluindo seleção/validação do
  banco, timeout, preservação de resposta parcial e ausência de aprovação
  automática da qualidade. `completed` no JSON não significa resposta correta.

## Revisão qualitativa pelo assistente

| Caso | Avaliação | Evidência / pendência |
| --- | --- | --- |
| database_with_distractions | Parcial | Ignorou distrações, mas sugeriu mudanças por duplicidade sem justificativa e omitiu estratégia de criação concorrente e verificação do plano. |
| cache_with_distractions | Reprovado | O exemplo mistura chave de dados com lock e pode devolver o marcador `calculando` como dado; não garante a coordenação que promete. |
| network_diagnosis | Parcial | Inclui comandos de DNS, mas não distingue resolução de problemas de Host/TLS. Chama o arquivo de configuração do resolved de cache. |
| unintelligible_transcript | Reprovado | Inventou PostgreSQL, tabela e colunas a partir de palavras incompreensíveis, em vez de pedir esclarecimento. |
| csharp_async | Reprovado | Explica o básico, mas recomenda envolver leitura síncrona em Task.Run no endpoint, contrariando a orientação esperada. |
| dotnet_di | Parcial | Reconhece o problema de capturar DbContext, mas não explica a criação explícita de escopo e sugere repositórios sem resolver claramente o ciclo de vida. |
| ef_tracking | Reprovado | Afirma que AsNoTracking().FindAsync existe, atribui comportamento incorreto a Find e prevê exceções de SaveChanges sem fundamento no caso descrito. |
| dotnet_with_distractions | Parcial | Ignora o ruído e explica bloqueio, mas acrescenta uma recomendação confusa de AsTask como se resolvesse acesso não bloqueante ao resultado. |
| literal_not_distraction | Adequado ao caso | Preserva nomes explícitos e produz CREATE INDEX sem UNIQUE. O comando não foi executado em banco real. |
| sql_parameters | Parcial | Recomenda parâmetros separados do SQL; simplifica o mecanismo como escaping e não explica o limite para nomes de tabelas/colunas. |
| testing_strategy | Parcial | Distingue os três níveis, mas trata banco real e navegador como requisitos gerais de integração/E2E, embora o escopo possa variar. |
| incomplete_technology | Adequado ao caso | Pede stack e gargalo, apresentando as possibilidades como condicionais. |

Esta é revisão do texto gerado pelo assistente, não certificação humana nem
validação por compilação/execução. O JSON bruto mantém `quality_review=pending`
para que uma pessoa possa revisar independentemente. Os exemplos no prompt se
sobrepõem a alguns temas do banco; estes casos verificam regressão, não medem
generalização para perguntas inéditas.

## Referências usadas na revisão

- ASP.NET Core já executa requisições no pool; Task.Run não torna chamadas
  síncronas assíncronas nem evita o bloqueio de threads. [Microsoft](https://learn.microsoft.com/en-us/aspnet/core/fundamentals/best-practices).
- Serviços Scoped usados por Singletons exigem gestão explícita de escopo.
  [Ciclos de vida](https://learn.microsoft.com/en-us/dotnet/core/extensions/dependency-injection/service-lifetimes).
- AsNoTracking retorna IQueryable; entidades não rastreadas não têm alterações
  automaticamente detectadas por SaveChanges. [API](https://learn.microsoft.com/en-us/dotnet/api/microsoft.entityframeworkcore.entityframeworkqueryableextensions.asnotracking),
  [rastreamento](https://learn.microsoft.com/en-us/ef/core/querying/tracking).
- Locks Redis precisam de aquisição e liberação coerentes com a expiração e
  propriedade do lock. O marcador de lock não substitui o valor do cache.
  [Padrão oficial](https://redis.io/docs/latest/develop/clients/patterns/distributed-locks/).
- Índices não UNIQUE aceitam duplicatas; criação concorrente tem condições e
  limitações próprias. [PostgreSQL](https://www.postgresql.org/docs/current/sql-createindex.html).

## Como ampliar

Adicione perguntas reais ao JSON, com um nome único, a pergunta e critérios de
resposta. Inclua tanto exemplos limpos quanto distrações, termos literais e
contexto insuficiente. Mantenha perguntas inéditas fora dos exemplos do prompt
para avaliar generalização. As falhas acima continuam abertas; o banco as torna
reproduzíveis, sem substituir a resposta do modelo por um gabarito fixo.
