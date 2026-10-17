# Validação de respostas sobre C# e .NET

## Método e limites

Três perguntas foram enviadas pelo campo de texto da interface Electron, com o modelo local Qwen3.5:9b. Os tempos abaixo são até a conclusão da resposta, não até o primeiro trecho. A tentativa por áudio sofreu interferência de outros sons do Windows; estes resultados não validam reconhecimento de voz nem resposta simultânea à fala. Os exemplos gerados não foram compilados.

| Pergunta | Tempo | Avaliação |
| --- | ---: | --- |
| Diferença entre async/await e Task.Run no ASP.NET Core | 69,44 s | Parcial: distingue espera por I/O de trabalho no pool, mas recomenda Task.Run para cálculos em requisições sem explicar o custo. |
| Singleton, Scoped e Transient; Scoped dentro de Singleton | 105,03 s | Parcial: descreve os ciclos básicos, mas recomenda resolver Scoped via IServiceProvider sem criar um escopo. |
| AsNoTracking e efeitos em SaveChanges | 44,08 s | Reprovada tecnicamente: conceito básico correto, exemplo com API inválida e restrição inventada sobre Include. |

## Correções necessárias

- **ASP.NET Core:** envolver trabalho em `Task.Run` e imediatamente aguardá-lo não torna a requisição mais escalável; a execução já usa threads do pool. Para I/O, prefira APIs assíncronas nativas. Referência: [boas práticas do ASP.NET Core](https://learn.microsoft.com/en-us/aspnet/core/fundamentals/best-practices).
- **Injeção de dependências:** um Singleton que precise de um serviço Scoped deve criar e descartar um escopo explícito, por exemplo com `IServiceScopeFactory.CreateScope()`. Resolver diretamente pelo provedor raiz não corrige o problema. Referência: [ciclos de vida dos serviços](https://learn.microsoft.com/en-us/dotnet/core/extensions/dependency-injection/service-lifetimes).
- **EF Core:** `AsNoTracking()` retorna `IQueryable<T>`, que não oferece o método `FindAsync` do `DbSet`. Para esse exemplo, use `AsNoTracking().FirstOrDefaultAsync(c => c.Id == id)` e trate resultado nulo. `AsNoTracking` pode ser combinado com `Include`. Alterações em entidades não rastreadas não são automaticamente persistidas por `SaveChanges`. Referências: [API AsNoTracking](https://learn.microsoft.com/en-us/dotnet/api/microsoft.entityframeworkcore.entityframeworkqueryableextensions.asnotracking), [rastreamento de consultas](https://learn.microsoft.com/en-us/ef/core/querying/tracking), [consultas eficientes](https://learn.microsoft.com/en-us/ef/core/performance/efficient-querying).

## Retomada

Na retomada, o aplicativo foi reaberto e a terceira pergunta foi reenviada. A configuração ativa passou a usar o provedor OpenAI. A tentativa terminou em 1,55 s com a mensagem de limite de uso ou créditos, sem produzir resposta.

O código atual associa essa mensagem a qualquer HTTP 429; o registro disponível não permite distinguir limite de requisições de cota/créditos. Os três resultados anteriores pertencem ao modelo local, não ao provedor da nova tentativa. Nenhuma configuração de provedor foi alterada durante esta retomada.

## Histórico e latência: validação posterior

Após implementar cartões de histórico e geração completa em uma chamada, foram executados `npm test` (6 testes), `npm run typecheck`, `npm run build`, `.venv/Scripts/python.exe -m pytest tests -q` (35 testes) e `git diff --check`, todos com sucesso. Os testes de provedor usam respostas HTTP simuladas: verificam streaming, número de chamadas e propagação de falhas, não a precisão do modelo.

Na interface Electron real, duas simulações consecutivas produziram dois cartões com as respostas completas. Reiniciar o backend preservou ambos no histórico. Uma pergunta real posterior pela interface terminou com o mesmo erro 429 em 1,23 s, preservando os dois cartões anteriores. As simulações estavam explicitamente identificadas como simulação.

Uma chamada isolada ao Ollama/Qwen3.5:9b sobre async/await e Task.Run produziu o primeiro trecho em 12,83 s e concluiu em 17,61 s, medidos com relógio monotônico. A execução anterior sobre esse tema terminou em 69,44 s. Não é um benchmark controlado: o prompt de entrevista mudou entre execuções, o estado de aquecimento pode diferir e o terminal substituiu acentos da pergunta por `?` na chamada isolada. O ganho observado não valida a latência da API OpenAI, da transcrição ou da conversa completa, nem garante precisão técnica; a nova resposta ainda simplifica excessivamente o uso de Task.Run no ASP.NET Core.

O histórico permanece apenas em memória durante a janela aberta, inclusive após reconexões; recarregar ou fechar o aplicativo o apaga.
