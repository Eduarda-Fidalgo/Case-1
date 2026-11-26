# Case-1 · AI Incident Commander (Epic AI Recruiting Hackathon — Desafio Glintt)

Agente de IA que lê os registos de um hospital (`hospital.log`, 24h, 6 874 linhas JSON), decide o que é importante,
dá o alarme quando necessário e comunica o resto num relatório de fim de dia.

## Entregáveis
| Entregável (PDF) | Ficheiro | Estado |
|---|---|---|
| Requisitos, checklist e armadilhas | [`docs/01-desafio-e-requisitos.md`](docs/01-desafio-e-requisitos.md) | ✅ |
| Compreensão dos dados | [`docs/02-analise-dos-dados.md`](docs/02-analise-dos-dados.md) | ✅ |
| **Mínimo** — níveis de urgência e resposta | [`docs/03-niveis-de-urgencia.md`](docs/03-niveis-de-urgencia.md) | ✅ |
| **Mínimo** — incidentes (quando, onde, urgência, motivo) | [`docs/04-incidentes.md`](docs/04-incidentes.md) | ✅ |
| **Mínimo** — orientações e ferramentas | [`docs/05-orientacoes-e-ferramentas.md`](docs/05-orientacoes-e-ferramentas.md) | ✅ |
| Desenho do agente + bónus tempo real + extras | [`docs/06-arquitetura-do-agente.md`](docs/06-arquitetura-do-agente.md) | ✅ |
| Ground truth para avaliação automática | [`ground_truth/incidentes_esperados.json`](ground_truth/incidentes_esperados.json) | ✅ |
| **Bónus** — agente (código), alertas emitidos, relatório final | `agent/`, `output/alerts.jsonl`, `output/relatorio_fim_de_dia.md` | ⏳ próxima fase |
| **Bónus** — agente ativo em tempo real (replay linha a linha, 1 alerta por problema) | `python -m agent replay hospital.log` | ⏳ próxima fase |
| **Bónus** — extras (dashboard, previsão, PII, auto-avaliação) | `dashboard/`, `tests/` | ⏳ próxima fase |

## Resumo dos incidentes do dia
| Nível | # | Incidentes |
|---|---|---|
| 🔴 P1 | 4 | Login indisponível (IdP) · Laboratório sem resultados 2h25 (HL7, só em DEBUG) · EHR indisponível por pool BD esgotado · 38 prescrições sem verificação de dose |
| 🟠 P2 | 4 | Regressão portal 2.14.0 · Fuga de memória scheduling (OOM ~02:30) · Backlog fila admissões · Dados pessoais nos logs (RGPD) |
| 🟡 P3 | 4 | Certificado SAML (15/12) · Disco archive (~5,7 dias) · Pontos cegos da monitorização · Conta bloqueada |
| 🔵 P4 | 8 | Endpoint deprecado, query lenta, transitórios de deploy, QA em produção, … |

Detalhe e evidências: [`docs/04-incidentes.md`](docs/04-incidentes.md).

## MVP — run it
```bash
python3 agent/commander.py                 # batch: writes output/alerts.jsonl, output/report.md, web/data.js
python3 agent/commander.py --live 600      # real-time replay in the terminal (x600)
```
Open `web/index.html` (live replay, incidents by urgency, messages, day/week history, log validation, end-of-day report).

### Live web app (real-time input, acknowledge, re-notify, play again, validation)
```bash
python3 agent/server.py --speed 600        # open http://localhost:8000 - replays the FULL hospital.log line by line
python3 agent/server.py --follow /tmp/live.log & python3 agent/producer.py --to-file /tmp/live.log   # true tail of a growing file
python3 agent/evaluate.py                  # validate emitted alerts vs ground truth (12/12 detected, 8/8 on time, 0 dup, 0 PII)
```
Pitch (2 min): `pitch/AI_Incident_Commander_pitch.pptx` (speaker notes with timings).
