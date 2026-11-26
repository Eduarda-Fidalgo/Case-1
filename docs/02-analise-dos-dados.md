# 02 · Análise do ficheiro `hospital.log`

## Formato
- **6 874 linhas**, uma por evento, **JSON válido em todas** (0 linhas corrompidas), UTF-8.
- Ordenado cronologicamente (0 inversões). Período: `2026-11-25T00:00:00.403Z` → `2026-11-26T00:00:16.958Z` (UTC).
- Campos comuns a todas as linhas: `timestamp`, `level`, `service`, `host`, `trace_id`, `message`.
- Campos específicos variam por tipo de evento (~100 chaves distintas, 54 "formas" de linha).
- `trace_id` é único por linha, exceto `b086e873` (pedido falhado + retry com sucesso no portal).

## Níveis de log
| Nível | Linhas | Nota |
|-------|-------:|------|
| INFO  | 5 764 | inclui incidentes graves (ex.: `dose_check: bypass`, `pool reinit`, `config reloaded`) |
| ERROR | 422 | maioria explicada por 3 incidentes; há `ERROR` que é ruído (`file vanished during backup`) |
| WARN  | 345 | mistura de sinais reais e ruído recorrente (`deprecated endpoint`) |
| DEBUG | 343 | inclui a **desconexão HL7** (incidente crítico) e *dumps* de auditoria que parecem stack traces mas são inofensivos |

## Serviços e hosts (23 serviços, 28 pares serviço/host)
| Serviço | Hosts | Linhas | O que emite |
|---|---|---:|---|
| clinical-record | cr-01, cr-02, cr-03 | 1 422 | `record opened`, `request failed`, `acquire timeout`, heap/gc, `config reloaded` |
| auth | auth-01, auth-02 | 979 | `login succeeded/failed`, `upstream connect timeout`, `account locked`, cert |
| patient-portal | pp-01, pp-02 | 738 | `request completed/failed`, `unhandled exception`, heap/gc |
| lab-interface | lab-01 | 658 | `result received`, `hourly stats`, listener HL7 |
| scheduling | sch-01 | 519 | `appointment booked`, heap (15 min), gc |
| emergency-dept | eme-01 | 430 | triagem/admissão/alta (prioridades Manchester), `hourly stats` |
| admissions | adm-01 | 384 | `queue depth` (5 min), heap/gc |
| cache | cac-01 | 294 | DEBUG miss/evict, `hourly stats` |
| prescriptions | rx-01 | 288 | `prescription issued` com `dose_check` |
| integration-gateway | int-01 | 185 | `request forwarded`, `deprecated endpoint called` |
| billing | bil-01 | 178 | faturas, `hourly stats`, `request failed` |
| imaging | ima-01 | 158 | `study stored`, `hourly stats` |
| monitoring-agent | mon-01 | 144 | `health sweep completed` (10 min) |
| clinical-record-db | db-01 | 135 | `connection pool usage` (10 min), `pool reinit` |
| message-broker | mq-01, mes-01 | 88 | reconexões de consumidor, `hourly stats` |
| system-monitor | file-01 | 73 | `disk usage` (3 mounts, horário) |
| audit | aud-01 | 72 | DEBUG `audit batch flushed` com *dump* |
| pharmacy | ph-01 | 65 | `stock sync completed` (30 min), `sync incomplete` |
| notifications | not-01 | 24 | `hourly stats` |
| reports | rep-01 | 22 | `slow query` |
| load-balancer | lb-01 | 12 | health checks |
| backup | bkp-01 | 3 | backup noturno |
| deployer | ci-01 | 3 | deploys (reports 10:05, billing 11:40, patient-portal 16:40) |

## Séries periódicas (baselines úteis para o agente)
| Série | Periodicidade | Baseline normal | O que aconteceu |
|---|---|---|---|
| `clinical-record-db` pool `usage_pct` | 10 min | 18–35 % noite, 40–58 % dia | Pico 86 % às 02:30 (backup); **subida linear 71→96 % entre 10:00 e 13:30**; **silêncio 13:30–15:21**; reinit 15:21 |
| `scheduling` heap `heap_used_pct` | 15 min | (outros JVM: 41–49 % estável) | **38 → 91 % em 24h, a acelerar** |
| `scheduling` gc `pause_ms` (G1 Old) | ~15 min | outros JVM: ≤45 ms | **25 ms → 1 400 ms** |
| `admissions` `queue depth` | 5 min | 3–10 | Pico 125 às 09:20 (auto-recuperou 09:45); **14:00→23:55 sobe 10→480** (produzido ~34/min > consumido ~28/min) |
| `system-monitor` `/var/lib/archive` | 1 h | — | 86,0 → 88,0 % (+~2,1 p.p./dia). `/` ~41 % e `/var/log` ~55 % estáveis |
| `lab-interface` `result received` | evento | ~1/min em horário diurno | **0 resultados 10:47→13:12** |
| `pharmacy` `stock sync completed` | 30 min | ~18 300–18 500 itens | **sem sync 14:45→16:31**; `sync incomplete` a cada 5 min 15:00–16:30 |
| `auth` `login succeeded` | evento | ~30–60/h diurno | **0 sucessos 07:56→08:25** |
| `clinical-record` `record opened` | evento | ~100/h diurno, mediana ~100 ms | **apenas 5 na hora das 14h** |

## Sinais "enganadores" (contam para o relatório como ruído/falsos positivos)
- `monitoring-agent` `health sweep completed`: **144/144 com `failed_checks: 0`**, mesmo durante 4 incidentes críticos.
- `hourly stats` (lab, billing, ED, imaging, cache, notifications, broker): **`errors: 0` sempre**, incluindo horas com outage
  (ex.: lab 11:00–13:00 = `received: 0, rejected: 0`; billing 11–12h = 0 erros apesar de 4 × 503). Os números de `processed`
  são aleatórios e não acompanham a atividade real → **não usar como fonte de verdade**.
- `audit` DEBUG: 72 *dumps* que parecem stack traces (`at pt.audit.Writer.flush…`) mas são `state=FLUSHED` — inofensivos.
- `backup` ERROR `file vanished during backup` (`/tmp/.app.lock`) — ficheiro temporário; backup terminou `ok` (412 GB).
- `load-balancer` `health check failed` ×5 em `rep-02` (10:05) e `pp-02` (16:40) — *rolling deploy*, recuperou em <2 min.
  ⚠️ No caso do portal, o LB ficou verde **mas a aplicação ficou partida** (health check não testa o fluxo de negócio).
- `integration-gateway` `deprecated endpoint called` ×48 (sempre o mesmo cliente/endpoint) — repetitivo.
- `message-broker` reconexões do consumidor `notifications` ×32 (~cada 45 min, <1,8 s, 0 dead letters).
- `auth` `BAD_CREDENTIALS` dispersos (26 fora do caso u0814) — normal.
- `patient-portal` `request failed` 12:14 + `request retried` (mesmo trace) — transitório resolvido por retry.

## Dados pessoais no log
- Normal: pseudónimos (`patient_ref` PR-xxxxx, `user` uxxxx, `order_ref`, `episode_ref`). Chaves de cache `patient:PR-…`.
- **Anómalo**: 12 linhas `record opened` em `cr-03` (11:19–11:49) com `ctx` contendo **nome completo, nº de identificação
  civil e data de nascimento** (linhas 3170–3364). Ver incidente INC-08. **Estes valores nunca devem ser copiados para
  alertas, relatórios ou prompts de LLM.**

## Cronologia de eventos de mudança (contexto para correlação)
| Hora (UTC) | Evento |
|---|---|
| 02:00–03:15 | Backup noturno (`nightly-full`), pool BD sobe a 86 % e desce |
| 06:00 | Aviso certificado SAML (expira 2026-12-15) e disco archive >85 % |
| 07:56–08:25 | IdP `idp-02:8443` inacessível |
| 10:05 | Deploy `reports` 5.3.0 → 5.3.1 |
| 10:47 | Lab: `HL7 listener: peer closed connection` (DEBUG) |
| 11:19 | `cr-03` `config reloaded` `log_ctx=verbose` por `deploy-bot` |
| 11:40 | Deploy `billing` 3.7.2 → 3.8.0 |
| 11:53 | `cr-03` `config reloaded` `log_ctx=default` por `ops.oncall` |
| 13:12 | Lab: listener HL7 reiniciado, backlog de 137 mensagens |
| 15:21 | `pool reinit` da BD por `ops.oncall` |
| 16:40 | Deploy `patient-portal` 2.13.4 → 2.14.0 |
