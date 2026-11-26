# 05 · Orientações e ferramentas utilizadas

## Orientações (princípios de triagem que o agente aplica)
1. **Impacto clínico primeiro.** Urgência = segurança do doente × alcance × tempo até ao dano. O `level` do log é só uma pista.
2. **Um problema = um alerta.** Agregar por (serviço, tipo de sinal, causa provável). Repetições aumentam um contador;
   pioria gera *update* de escalamento; normalização gera *update* "resolvido".
3. **O silêncio também é sinal.** Cada série/feed tem uma cadência esperada; ausência prolongada em horário de atividade = incidente.
4. **Tendência > limiar.** Para recursos (heap, pool, disco, filas) calcular declive e **tempo até esgotar**; alertar pelo prazo, não pela percentagem.
5. **Desconfiar das métricas agregadas.** `hourly stats`, `health sweep` e projeções do próprio sistema são verificadas contra os eventos brutos.
6. **Mudanças são suspeitas.** Deploys e `config reloaded` abrem uma janela de vigilância; erros **novos** nessa janela são atribuídos à mudança.
7. **Correlacionar antes de notificar.** Sinais simultâneos (ex.: `dose_check: bypass` + `pharmacy sync incomplete`) formam um único incidente com hipótese de causa.
8. **Valores nunca vistos.** Um valor categórico novo num campo de segurança (`dose_check=bypass`) é tratado como alerta imediato.
9. **Privacidade por defeito.** PII é detetada e **redigida** antes de qualquer saída ou envio a um LLM; o próprio vazamento é um incidente.
10. **Explicar sempre**: o quê, desde quando, porque importa, ação sugerida, quem foi notificado, evidência (linha/trace_id).
11. **Determinismo onde importa, LLM onde acrescenta.** Deteção e classificação = regras determinísticas, testáveis e auditáveis;
    LLM = redação de alertas/relatório e explicação, nunca a decisão de acordar alguém sozinho.

## Ferramentas utilizadas nesta fase (análise)
| Ferramenta | Para quê |
|---|---|
| Claude Code (agente de IA) | Leitura do PDF do desafio, exploração do log, hipóteses e documentação |
| Python 3 (`json`, `collections`, `statistics`, `datetime`) | Parsing das 6 874 linhas, contagens por serviço/mensagem/nível, séries temporais, deteção de lacunas, regex de PII |
| `grep` / `sed` | Localização de evidências por número de linha |
| Git / GitHub | Versionamento dos entregáveis |

### Método de análise aplicado
1. Validação do formato (JSON por linha, ordenação, campos comuns).
2. Inventário: contagem por `level`, `service`, `host`, (`service`,`message`), chaves raras.
3. Leitura integral de todos os eventos raros (≤6 ocorrências) e de todas as linhas com chaves raras.
4. Séries temporais de todas as métricas periódicas (pool, heap, GC, fila, disco, sync, hourly stats).
5. Deteção de **lacunas** (silêncio) por serviço e por tipo de evento.
6. Distribuições categóricas (ex.: `dose_check`, `reason`, `error`, `priority`, `ctx`) para encontrar valores anómalos.
7. Correlação temporal com eventos de mudança (deploys, config reloads, reinit).
8. Pesquisa de PII e de tentativas de *prompt injection* no texto livre (nenhuma injeção encontrada; PII encontrada).

## Ferramentas previstas para a solução (fase seguinte)
| Componente | Tecnologia proposta |
|---|---|
| Agente / motor de regras | Python 3.11+ (sem dependências pesadas) |
| Replay em tempo real | Gerador assíncrono (`asyncio`) que respeita os intervalos dos timestamps, com fator de aceleração |
| Explicações e relatório | API Claude (modelo mais recente) com *fallback* para templates determinísticos se não houver chave/API |
| Alertas | `output/alerts.jsonl` + consola colorida + (opcional) webhook/Slack/Teams/email simulados por nível |
| Dashboard ao vivo (extra) | Página HTML servida localmente (SSE/WebSocket) com timeline de incidentes |
| Testes | `pytest` + avaliação contra `ground_truth/incidentes_esperados.json` (precisão, recall, atraso de deteção, duplicados, PII) |
