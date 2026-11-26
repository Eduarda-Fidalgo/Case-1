# 01 · Desafio e requisitos — AI Incident Commander

Fonte: `GLINTT - EPIC AI RECRUITING HACKATHON.pdf` (Desafio Glintt, 26/11/2026) + `hospital.log`.

## Problema (resumo)
Um hospital funciona 24h com software (registo clínico, laboratório, prescrições, admissões,
consultas, urgência…). Cada sistema gera registos e hoje são pessoas a analisá-los:
- os problemas reais são detetados **tarde**;
- o **ruído inofensivo** recebe atenção que não merece;
- os problemas que **se acumulam lentamente** passam despercebidos até algo avariar.

`hospital.log` = um dia inteiro (24h, linhas JSON). Algumas situações exigem **intervenção imediata**,
outras **podem esperar pelo fim do dia**, outras **apenas parecem assustadoras**.

Queremos um **comandante de incidentes baseado em IA**: lê os registos, decide o que é importante,
**dá o alarme quando necessário** e **comunica o resto no fim do dia**.

## Jobs to be Done (checklist)
| # | Job | Onde fica respondido |
|---|-----|----------------------|
| J1 | Encontrar os incidentes nos registos do dia | `docs/04-incidentes.md`, `ground_truth/incidentes_esperados.json` |
| J2 | Classificar cada um por urgência **e explicar porquê** | `docs/04-incidentes.md` (coluna "Porquê") |
| J3 | Definir os nossos níveis de urgência e a resposta: **quem** é notificado, **como**, **com que rapidez** | `docs/03-niveis-de-urgencia.md` |
| J4 | Criar um agente que aplique a triagem ao registo: emite **alertas com breve explicação** e elabora o **relatório de fim de dia** | `docs/06-arquitetura-do-agente.md` (desenho) → código na fase seguinte |

## Bónus
| # | Requisito | Como vamos cumprir |
|---|-----------|--------------------|
| B1 | **Tempo real**: reproduzir o registo linha a linha, como se estivesse a chegar | *Replayer* que lê `hospital.log` e emite linhas respeitando os timestamps (com fator de aceleração, ex.: 24h → ~2 min) |
| B2 | Emitir cada alerta **no momento em que deve ser emitido** | Deteção incremental (regras de estado + janelas temporais + tendências), sem "olhar para o futuro" |
| B3 | **Uma vez por problema** | Chave de deduplicação por incidente (serviço + tipo + janela), com estados `aberto → escalado → resolvido`; escalamentos e resolução são *updates* do mesmo incidente, não alertas novos |
| B4 | **Surpreende-nos!** | Ver secção "Extras" em `docs/06-arquitetura-do-agente.md` (dashboard ao vivo, redação de PII, correlação causal, previsão de rutura, deteção de silêncio, avaliação automática contra ground truth) |

## Entregáveis exigidos
### 1 · Mínimo
- [x] Os incidentes encontrados: **quando, onde, nível de urgência e motivo** → `docs/04-incidentes.md`
- [x] Os níveis de urgência e a resposta a cada um → `docs/03-niveis-de-urgencia.md`
- [x] As orientações e ferramentas utilizadas → `docs/05-orientacoes-e-ferramentas.md`

### 2 · Bónus
- [ ] O agente (código ou configuração), **os alertas que emitiu** e **o relatório final do dia** → fase seguinte (`agent/`, `output/alerts.jsonl`, `output/relatorio_fim_de_dia.md`)
- [ ] Agente **ativo** que monitoriza o registo à medida que é recebido e emite alertas **de forma autónoma**
  ("colar o ficheiro num chat é o ponto de partida, não o ponto final") → fase seguinte (`replay` + `agent run --live`)
- [ ] Tudo o que for além disso → extras

## Detalhes a não esquecer (armadilhas identificadas no PDF + dados)
1. **Severidade do log ≠ urgência real.** Dois dos incidentes mais graves estão em `DEBUG` e `INFO`
   (desconexão HL7 do laboratório; prescrições com `dose_check: bypass`). Há `ERROR`s que são ruído.
2. **Ausência de logs é um sinal.** O laboratório deixa de receber resultados durante 2h25 e as métricas
   da BD deixam de ser emitidas durante 1h51 — nada disto gera erro.
3. **Problemas lentos**: fuga de memória (scheduling), fuga de ligações (BD), backlog de fila (admissions),
   disco (archive), certificado SAML — exigem análise de **tendência/projeção**, não limiares.
4. **Os próprios sistemas de monitorização mentem**: `health sweep` reporta sempre 0 falhas; `hourly stats`
   reportam 0 erros durante incidentes; a projeção de disco do `system-monitor` (14 dias) está errada (~5,7 dias).
5. **Dados pessoais (RGPD)** apareceram no log (nome, nº identificação, data de nascimento). O agente
   **não pode** reproduzi-los em alertas/relatório — tem de os **redigir**.
6. **"Uma vez por problema"** — 159 falhas de login são **1** incidente, não 159 alertas.
