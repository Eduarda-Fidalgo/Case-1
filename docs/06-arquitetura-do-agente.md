# 06 · Arquitetura do agente (desenho para a fase de implementação)

## Visão geral
```
hospital.log ──► Replayer ──► Ingestor ──► Redator PII ──► Detetores ──► Gestor de Incidentes ──► Notificador
 (ficheiro)     (linha a linha,  (parse +    (mascara      (regras +      (dedup, estado,         (consola, alerts.jsonl,
                 ritmo real ×N)   relógio)    nm/nid/dob)   estado por     escalamento,            canais simulados por nível,
                                                            série)         correlação)             dashboard)
                                                                                 │
                                                                                 └──► Relatório de fim de dia (00:00 / EOF)
                                                                                       (template + LLM opcional)
```
- **Relógio lógico** = timestamp da última linha lida. Detetores de silêncio/tendência correm a cada "tick" do relógio,
  não apenas quando chega uma linha (senão o silêncio nunca dispara).
- **Sem olhar para o futuro**: cada decisão usa apenas linhas já recebidas → o mesmo código corre em batch e em tempo real.

## Modos de execução
| Comando (previsto) | Comportamento |
|---|---|
| `python -m agent replay hospital.log --speed 600` | Reproduz o log com ritmo real acelerado (24h ≈ 2,4 min) e o agente emite alertas no momento |
| `tail -f hospital.log \| python -m agent run --stdin` | Agente ativo sobre um *stream* real |
| `python -m agent batch hospital.log` | Mesma lógica, sem esperas (para testes) |
| `python -m agent evaluate` | Compara `output/alerts.jsonl` com `ground_truth/` |

## Detetores (cada um mapeado a incidentes reais)
| Detetor | Lógica | Cobre |
|---|---|---|
| `DependencyOutage` | ≥3 `upstream connect timeout` ao mesmo upstream em ≤5 min **ou** taxa de falha de login > 80 % em 2 min com ≥10 tentativas | INC-01 |
| `FeedSilence` | Feed com cadência esperada (resultados lab, logins, record opened, métricas periódicas) sem eventos > max(15 min, 5× intervalo mediano) em horário diurno; reforçado por eventos de desconexão (mesmo em DEBUG) | INC-02, silêncio da BD em INC-03 |
| `ResourceTrend` | Regressão linear em janela deslizante (pool, heap, disco, filas); alerta por **tempo até esgotar** (<4 h → P1/P2, <24 h → P2, <14 d → P3); GC pause vs baseline de outros JVM | INC-03, INC-06, INC-07, INC-10 |
| `ErrorBurst` | Contagem de `ERROR`/`acquire timeout`/HTTP 5xx por (serviço, código) em janela de 5 min vs baseline | INC-03 (escalamento), transitórios P4 |
| `ChangeRegression` | Janela de 2 h após `deployed`/`config reloaded`: nova assinatura de erro (`error`/`stack`) nunca vista antes → atribui à mudança; taxa de falha por *path* | INC-05, billing P4 |
| `SafetyControl` | Valores novos em campos de segurança (`dose_check != pass`) → P1 imediato; correlaciona com `pharmacy` | INC-04 |
| `PIILeak` | Regex em todo o texto livre (`nm=`, `nid=`, `dob=`, nº de 8–9 dígitos, datas de nascimento, nomes) + correlação com `log_ctx=verbose` | INC-08 |
| `Expiry` | `days_left`, `not_after`, `sunset`, `projected_full_days` (recalculado pelo detetor de tendência) | INC-09, INC-10, P4 deprecado |
| `AuthAbuse` | ≥5 `BAD_CREDENTIALS` mesmo utilizador em 5 min; ≥N utilizadores distintos do mesmo período (spraying) | INC-12 |
| `MonitorTrust` | Contradições: `health sweep` 0 falhas com incidente aberto; `hourly stats` 0 erros com erros contados | INC-11 |
| `NoiseFilter` | Lista de padrões conhecidos benignos (backup lock, LB durante deploy, audit dump, reconexões curtas) → contados, não alertados | Ruído |

## Gestor de incidentes
- **Chave de dedup**: `(tipo_detetor, serviço, recurso/upstream/campo)`.
- **Estados**: `aberto` → `escalado` → `resolvido` (+ `ativo no fim do dia`).
- **Emissão**: 1 alerta ao abrir; *updates* só em escalamento e resolução (com duração, contagem de eventos, impacto).
- **Correlação**: incidentes abertos com sobreposição temporal e dependência conhecida (ex.: prescriptions↔pharmacy, clinical-record↔db)
  fundem-se num só com "causa provável".
- **Supressão de cascata**: erros a jusante de um incidente aberto (ex.: HTTP 500 do clinical-record durante pool esgotado) não abrem incidentes novos.

## Notificador (resposta por nível — ver `docs/03-niveis-de-urgencia.md`)
| Nível | Canais simulados |
|---|---|
| P1 | `PAGER`+`SMS` on-call, `CALL` chefe de equipa clínica, canal `#war-room` |
| P2 | `PUSH` on-call, canal da equipa, ticket prioritário (+ `EMAIL` DPO se PII) |
| P3 | Ticket + relatório |
| P4 / Ruído | Relatório |

Cada alerta em `output/alerts.jsonl`:
```json
{"alert_id":"INC-02","emitted_at":"2026-11-25T11:02:00Z","status":"aberto","nivel":"P1",
 "servico":"lab-interface","hosts":["lab-01"],"inicio":"2026-11-25T10:47:12Z",
 "titulo":"Laboratório sem resultados há 15 min","explicacao":"…","impacto":"…","acao":"…",
 "notificados":["oncall-integracao","resp-laboratorio","chefe-equipa-clinica"],
 "canais":["PAGER","SMS","CALL"],"evidencia":[{"linha":2964,"trace_id":"a3735e4e"}]}
```

## Relatório de fim de dia (`output/relatorio_fim_de_dia.md` + versão HTML)
1. Sumário executivo (3–5 linhas): estado no fim do dia, nº de incidentes por nível, o que está ativo.
2. **Ações para a próxima manhã / noite** (ex.: restart scheduling antes das 02:00; rollback portal; drenar fila admissões; revisão das 38 prescrições).
3. Linha do tempo dos incidentes (P1–P2) com deteção, escalamento, resolução, duração, MTTD do agente vs. sinal original.
4. Tabela P3 (com prazos) e P4.
5. Ruído suprimido (contagens por padrão) — mostra o valor da filtragem.
6. Saúde da monitorização (INC-11) e recomendações.
7. Anexo: lista de `patient_ref` afetados (INC-04, INC-02) — pseudónimos, nunca PII.

## Uso do LLM (Claude)
- **Entrada**: incidente estruturado (já classificado) + até N linhas de evidência **redigidas**.
- **Saída**: título, explicação breve, impacto, ação sugerida (pt-PT). Relatório final a partir da lista de incidentes.
- **Proteções**: o texto dos logs é tratado como **dados**, nunca como instruções (delimitado no prompt); *fallback* para templates
  se a API falhar; o nível de urgência é sempre o do motor de regras (o LLM não pode baixá-lo).

## Extras ("Surpreende-nos!")
1. **Dashboard ao vivo**: timeline 24h com incidentes a acender à medida que o replay avança, contadores de ruído suprimido, sparklines (pool, heap, fila).
2. **Previsão de rutura** com hora estimada (heap scheduling → ~02:30; disco archive → ~1 dez.), corrigindo a projeção errada do monitor.
3. **Correlação causal** e "cadeia do dia" (login → lab → EHR → prescrição → portal).
4. **Redação automática de PII** + o próprio vazamento como incidente.
5. **Auto-avaliação**: `evaluate` mede recall, precisão, atraso de deteção vs `detect_by`, duplicados e fugas de PII.
6. **Comparação com a monitorização atual**: "o agente detetou X P1; o monitoring-agent reportou 0 falhas".
7. **Runbooks** por tipo de incidente ligados a cada alerta.

## Estrutura de repositório prevista
```
case-1/
├── README.md
├── hospital.log
├── docs/                         # entregáveis mínimos (feitos)
├── ground_truth/incidentes_esperados.json
├── agent/                        # (fase seguinte) código do agente
│   ├── __main__.py  replay.py  ingest.py  pii.py
│   ├── detectors/  incidents.py  notifier.py  report.py  llm.py
├── tests/                        # (fase seguinte)
├── dashboard/                    # (fase seguinte, extra)
└── output/                       # (gerado) alerts.jsonl, relatorio_fim_de_dia.md/.html
```
