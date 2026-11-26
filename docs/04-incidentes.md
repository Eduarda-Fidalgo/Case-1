# 04 · Incidentes encontrados (25/11/2026, UTC)

Legenda: **Linhas** = números de linha em `hospital.log` (evidência). **Deteção ideal em tempo real** = o momento
em que o agente (a ler linha a linha, sem ver o futuro) deve emitir o alerta — é o alvo para o bónus.

## Resumo
| ID | Nível | Quando | Onde | Incidente |
|---|---|---|---|---|
| INC-01 | 🔴 P1 | 07:56 → 08:25 (29 min) | auth (auth-01, auth-02) → IdP `idp-02:8443` | Ninguém consegue fazer login (troca de turno) |
| INC-02 | 🔴 P1 | 10:47 → 13:12 (2h25) | lab-interface / lab-01 | Ligação HL7 caiu em silêncio — 0 resultados laboratoriais |
| INC-03 | 🔴 P1 (P2 desde 10:00) | 10:00 → 15:21 | clinical-record-db / db-01 → clinical-record cr-01/02/03 | Fuga de ligações esgota pool → processo clínico eletrónico indisponível |
| INC-04 | 🔴 P1 | 15:02 → 16:27 (85 min) | prescriptions / rx-01 (+ pharmacy / ph-01) | 38 prescrições emitidas **sem verificação de dose** |
| INC-05 | 🟠 P2 | 16:40 → fim do dia (ativo) | patient-portal pp-01/pp-02 | Deploy 2.14.0 partiu a confirmação de consultas |
| INC-06 | 🟠 P2 | 00:00 → fim do dia (ativo) | scheduling / sch-01 | Fuga de memória: heap 38 → 91 %, GC 25 ms → 1,4 s; rutura prevista ~02:30 de 26/11 |
| INC-07 | 🟠 P2 | 14:00 → fim do dia (ativo) | admissions / adm-01 (`admissions.events`) | Backlog crescente na fila: 10 → 480 mensagens |
| INC-08 | 🟠 P2 (RGPD) | 11:19 → 11:53 | clinical-record / cr-03 | Dados pessoais de 12 doentes escritos em claro nos logs |
| INC-09 | 🟡 P3 | aviso 06:00; prazo 15/12/2026 | auth / auth-01 | Certificado SAML de assinatura expira em 20 dias |
| INC-10 | 🟡 P3 | aviso 06:00; contínuo | system-monitor / file-01 `/var/lib/archive` | Disco a 88 %; enche em **~5–6 dias** (monitor diz 14) |
| INC-11 | 🟡 P3 | todo o dia | monitoring-agent, hourly stats, níveis de log | Pontos cegos de observabilidade |
| INC-12 | 🟡 P3 | 13:40 → 13:41 | auth / auth-01 | Conta `u0814` bloqueada após 8 passwords erradas em 82 s |

---

## 🔴 INC-01 — Indisponibilidade de login (IdP)
- **Quando**: 07:56:00 → 08:25:30 (29,5 min). **Onde**: `auth` em `auth-01` e `auth-02`, upstream `idp-02:8443`.
- **O que aconteceu**: 29 `upstream connect timeout` (1/min, timeout 3000 ms), **159 `login failed` `UPSTREAM_TIMEOUT`** e
  **0 logins com sucesso** no período (smartcard e password). Recupera às 08:25:30 (`upstream connected`).
- **Porquê P1**: 100 % dos profissionais sem acesso aos sistemas durante a **troca de turno da manhã** (pico de logins);
  sem login não há acesso ao processo clínico, prescrição, etc.
- **Linhas**: 1219 (1.º timeout) · 1220–1602 (falhas) · 1609 (recuperação).
- **Deteção ideal**: ~07:58 (≥3 timeouts consecutivos ao mesmo upstream **e** falhas `UPSTREAM_TIMEOUT` em rajada sem sucessos).
- **Resposta**: on-call identidade + chefe de equipa clínica (ativar procedimentos de contingência/contas de emergência);
  verificar `idp-02`, failover para outro IdP. Pós-incidente: porque é que ambos os nós de auth dependem de um único IdP?

## 🔴 INC-02 — Laboratório sem resultados (falha silenciosa HL7)
- **Quando**: 10:47:12 → 13:12:40 (2h25). **Onde**: `lab-interface` / `lab-01`, peer `lab-analyzer-gw`.
- **O que aconteceu**: `HL7 listener: peer closed connection` registado **apenas em DEBUG**. Último resultado 10:46:59;
  nenhum resultado até 13:14:21. As `hourly stats` das 11h e 12h dizem `received: 0, rejected: 0, ack_errors: 0` (parece "limpo").
  Às 13:12:40 o listener é reiniciado e chega um **backlog de 137 mensagens**; latência média dessa hora 1 867 ms (normal ~100–150).
- **Porquê P1**: ocorre na hora de maior volume (09–10h: 92 resultados/h). Resultados como **troponina, INR, hemograma** ficam
  retidos 2h+ → decisões clínicas atrasadas (ex.: enfarte, anticoagulação). Sem erro nenhum — só se vê pela **ausência**.
- **Linhas**: 2964 (desconexão) · 2963 (último resultado antes) · 3800–3801 (reinício + backlog) · hourly stats 11:00/12:00/13:00.
- **Deteção ideal**: 10:47 aviso (desconexão sem reconexão) → **P1 ≤ 11:02** (15 min sem resultados em horário diurno, vs. baseline ~1/min).
- **Resposta**: on-call integração + responsável do laboratório + chefe de equipa clínica (laboratório comunica resultados
  críticos por telefone enquanto durar). Pós-incidente: reconexão automática do listener, alarme de "silêncio".

## 🔴 INC-03 — Esgotamento do pool de ligações da BD clínica → EHR indisponível
- **Quando**: degradação 10:00 → 13:30; falha 13:35 → 15:21. **Onde**: `clinical-record-db` / `db-01`; impacto em `clinical-record` cr-01, cr-02, cr-03.
- **O que aconteceu**:
  - 10:00 salto para 71 % e depois **subida linear (+~1 p.p./10 min)** até 96 % às 13:30 — padrão de **fuga de ligações**
    (às 09:50 estava a 56 %, normal).
  - **13:30 → 15:21 a BD deixa de reportar métricas** (111 min de silêncio).
  - 13:35 → 14:04: **69 `acquire timeout`** (E-DB-0412, 5 s).
  - 14:05 → 15:19: **113 `request failed` HTTP 500** (E-DB-0413) a abrir processos de doentes, nos 3 hosts.
  - Na hora das 14h só 5 processos abertos com sucesso (normal ~100/h).
  - 15:21 `pool reinit` manual por `ops.oncall` → pool volta a 12 % e depois 38–58 % (normal).
- **Porquê P1**: médicos e enfermeiros sem acesso ao processo clínico durante ~1h45 em horário diurno.
  Era **previsível desde ~11:00** (P2) — o problema "lento" que passa despercebido até avariar.
- **Linhas**: 2565 (1.º WARN 71 %) · 3171 (≥80 %) · 3919 (96 %, última métrica) · 3963 (1.º acquire timeout) ·
  4233–4810 (HTTP 500) · 4826 (pool reinit).
- **Deteção ideal**: **P2 ~11:00** (6 amostras consecutivas a subir, projeção 100 % antes das 14h) → **P1 às 13:35** (1.º acquire timeout)
  + alerta de silêncio de métrica às ~13:50.
- **Resposta**: P2 → DBA/on-call aplicação (identificar a origem da fuga, reciclar pool *antes* de esgotar).
  P1 → + chefe de equipa clínica (contingência papel). **Causa-raiz não resolvida** pelo reinit → follow-up obrigatório
  (hipótese a investigar: consultas `q_monthly_occupancy` lentas desde 09:06 a reter ligações).

## 🔴 INC-04 — Prescrições emitidas sem verificação de dose
- **Quando**: 15:02:43 → 16:27:30. **Onde**: `prescriptions` / `rx-01`; correlacionado com `pharmacy` / `ph-01`.
- **O que aconteceu**: **todas as 38 prescrições** emitidas neste período têm `dose_check: "bypass"` (as restantes 250 do dia
  têm `pass`), para 38 doentes distintos, por prescritores diferentes. Registado como **INFO**. Em simultâneo,
  a farmácia falha a sincronização de stock: último sync OK 14:45, `sync incomplete` (`status: partial`) a cada 5 min
  de 15:00 a 16:30 com cache a envelhecer até 95 min; recupera às 16:31.
- **Porquê P1**: risco direto de **erro de medicação** (sobredosagem, interações) — dano ao doente. Mesmo após o fim,
  as 38 prescrições continuam por validar.
- **Linhas**: 4657 (1.º sync incomplete) · 4688 (1.ª bypass) · 5338 (última bypass) · 5350 (último partial).
- **Deteção ideal**: **15:02:43** (primeira prescrição com `bypass` — valor nunca visto antes; correlacionar com farmácia).
- **Resposta**: responsável de farmácia/farmacêutico de serviço + diretor clínico + on-call aplicação: suspender ou exigir dupla
  validação manual; **revisão retrospetiva das 38 prescrições** (lista de `patient_ref` no relatório); restaurar o sync.

## 🟠 INC-05 — Regressão no portal do doente após deploy 2.14.0
- **Quando**: deploy 16:40 → ativo no fim do dia. **Onde**: `patient-portal` pp-01 e pp-02, `POST /appointments/confirm`.
- **O que aconteceu**: novo erro **`NullPointerException in SlotMapper`** (nunca visto antes do deploy), **104 falhas** até 23:56;
  após o deploy `/appointments/confirm` falha em **~86 %** (104 falhas vs 17 sucessos; antes: 101/101 com sucesso).
  O load balancer marcou pp-02 saudável às 16:42 — **health check não testa este fluxo**.
- **Porquê P2**: utentes não conseguem confirmar consultas (impacto em acesso a cuidados e ocupação de agenda), mas não há risco
  clínico imediato e existe alternativa (telefone/balcão). Continua ativo → não pode esperar pelo dia seguinte.
- **Linhas**: 5418 (deploy) · 5422–5435 (LB) · 5480 (1.º NPE) · 6860 (último).
- **Deteção ideal**: ~17:12 (2.ª ocorrência de assinatura de erro nova, <1h após deploy no mesmo serviço).
- **Resposta**: equipa do portal + release manager: **rollback para 2.13.4**; comunicação aos utentes.

## 🟠 INC-06 — Fuga de memória no scheduling (rutura iminente)
- **Quando**: todo o dia, a acelerar. **Onde**: `scheduling` / `sch-01`.
- **O que aconteceu**: heap 38,0 % (00:00) → 91,0 % (23:45), sempre a subir, ritmo atual ~3,2 p.p./h; pausas GC **G1 Old**
  25 ms → 1 400 ms (os outros JVM ficam ≤45 ms e heap estável 41–49 %). WARN só a partir de 20:15 (>80 %).
- **Porquê P2**: projeção de **heap a 100 % / OutOfMemory por volta das 02:00–03:00 de 26/11**, antes da abertura da marcação
  de consultas da manhã; pausas >1 s já degradam o serviço.
- **Linhas**: 1.ª amostra (linha 2), 6258 (1.º WARN), 6807–6808 (últimas: 91 %, GC 1 400 ms).
- **Deteção ideal**: P3 (tendência) ~06:00; **P2 quando projeção de esgotamento < 12 h (~14:00)**; escalar P1 se >95 % ou GC > 2 s.
- **Resposta**: equipa scheduling: heap dump + restart controlado em janela de baixo tráfego **antes das 02:00**; corrigir fuga.

## 🟠 INC-07 — Backlog crescente na fila de admissões
- **Quando**: 14:00 → ativo. **Onde**: `admissions` / `adm-01`, fila `admissions.events`.
- **O que aconteceu**: a partir das 14:00 produção ~32–36/min > consumo ~27–30/min; profundidade 10 → **480** (23:55), a crescer
  ~6/min (atraso estimado ~17 min e a aumentar). WARN só às 17:55 (≥200).
  (O pico das 09:05–09:45 até 125 recuperou sozinho — não é este incidente.)
- **Porquê P2**: eventos de admissão atrasados (gestão de camas, notificação aos serviços); tende a piorar e não recupera sozinho.
- **Linhas**: 4159 (14:00 início) · 5775 (1.º WARN) · 6855 (480).
- **Deteção ideal**: ~14:30 (profundidade a subir 6 amostras seguidas com produzido > consumido) → P2.
- **Resposta**: equipa admissões/integração: escalar consumidores, investigar aumento de produção (começa durante INC-03 — possível re-emissão de eventos).

## 🟠 INC-08 — Fuga de dados pessoais para os logs (RGPD)
- **Quando**: 11:19:05 → 11:53:02. **Onde**: `clinical-record` / `cr-03`.
- **O que aconteceu**: `config reloaded` com `log_ctx: "verbose"` por `deploy-bot` (11:19:05); em seguida **12 linhas** `record opened`
  com **nome completo, nº de identificação e data de nascimento** de 12 doentes no campo `ctx`. Revertido para `default` por
  `ops.oncall` às 11:53:02.
- **Porquê P2**: violação de dados pessoais de saúde (RGPD art. 33: avaliação e eventual notificação à CNPD em 72 h).
  Os logs podem já ter sido replicados (agregador, backups).
- **Linhas**: 3166 (verbose) · 3170–3364 (12 linhas com PII — **não reproduzir conteúdo**) · 3386 (revertido).
- **Deteção ideal**: **11:19:37** (1.ª linha com padrões `nm=`/`nid=`/`dob=`), correlacionada com a mudança de config.
- **Resposta**: DPO + Segurança + equipa clinical-record: purgar/mascarar logs em todas as cópias; rever a alteração do deploy-bot.

## 🟡 INC-09 — Certificado SAML a expirar
- 06:00:00, `auth-01`: `saml-signing` expira **2026-12-15** (20 dias). Se expirar, **todos** os logins SSO falham (pior que INC-01).
- Linha 639. **Resposta**: ticket à equipa de identidade com prazo; renovar ≥7 dias antes.

## 🟡 INC-10 — Disco do arquivo a encher (projeção errada do monitor)
- 06:00:03, `file-01` `/var/lib/archive` > 85 %; monitor diz `projected_full_days: 14`.
- **Dados reais**: 86,0 % (00:30) → 88,0 % (23:30) = ~2,1 p.p./dia → **cheio em ~5,7 dias (~1 de dezembro)**.
- Linhas 644, 6769. **Resposta**: ticket infraestrutura com prazo esta semana (expandir/limpar arquivo); corrigir o cálculo da projeção.

## 🟡 INC-11 — Pontos cegos da monitorização (meta-incidente)
- `monitoring-agent`: 144 sweeps, **sempre 0 falhas**, incluindo durante INC-01/02/03/04.
- `hourly stats` com `errors: 0` durante outages (lab 11h–13h; billing 11h com 4 × 503).
- Métricas da BD em silêncio 13:30–15:21 sem qualquer alarme.
- Eventos críticos registados em níveis baixos: desconexão HL7 em **DEBUG**; `dose_check: bypass` em **INFO**.
- LB health check verde com a aplicação partida (INC-05).
- **Resposta**: ticket observabilidade (relatório de fim de dia).

## 🟡 INC-12 — Conta bloqueada por tentativas falhadas
- 13:40:02 → 13:41:50, `auth-01`: `u0814` com 8 `BAD_CREDENTIALS` em 82 s → `account locked`.
- Caso isolado (sem padrão de ataque distribuído: os outros 26 `BAD_CREDENTIALS` estão dispersos por utilizadores e horas).
- Linhas 3985–4002. **Resposta**: helpdesk/segurança confirmam com o utilizador; sem notificação urgente.

---

## 🔵 P4 — Informativo (só relatório de fim de dia)
| Quando | Onde | Evento | Porquê P4 |
|---|---|---|---|
| todo o dia (48×) | integration-gateway, cliente `radiology-pacs` | Chama `/v1/patients` deprecado (sunset **2027-01-31**, ~67 dias) | Sem impacto atual; ticket de migração à equipa PACS |
| 09:06 → 17:50 (22×) | reports / rep-01 | `q_monthly_occupancy` 4–6 s (limiar 2 s) | Relatório não-clínico; possível ligação a INC-03 (investigar) |
| 11:40 → 11:42 | billing / bil-01 | 4 × HTTP 503 logo após deploy 3.8.0 | Transitório de deploy, resolvido em 2 min |
| 10:14 → 10:28 | patient-portal / pp-01 | 6 `unhandled exception` de `test.qa01` (`fixture missing`) | Testes de QA em produção — higiene (conta de teste em prod) |
| todo o dia (32×) | message-broker / mq-01 | Consumidor `notifications` reconecta ~cada 45 min (<1,8 s) | 0 dead letters; afinar keepalive |
| 01:30 → 03:20 | clinical-record-db | Pool sobe a 86 % durante backup noturno | Auto-recuperou; padrão esperado do backup |
| 09:05 → 09:45 | admissions | Pico de fila a 125 | Auto-recuperou em 40 min |
| 12:14 | patient-portal / pp-02 | `upstream timeout` + retry com sucesso (mesmo trace) | Transitório resolvido |

## ⚪ Ruído (suprimido, contado no relatório)
- `backup` ERROR `file vanished during backup` `/tmp/.app.lock` (linha 311) — lock temporário; backup `ok`.
- `load-balancer` `health check failed` ×10 durante rolling deploys (rep-02 10:05, pp-02 16:40) — recuperou < 2 min.
- `audit` DEBUG ×72 com texto tipo stack trace (`state=FLUSHED`).
- `cache` DEBUG miss/evict; `hourly stats` normais de todos os serviços.
- `auth` `BAD_CREDENTIALS` dispersos (26); `disk usage` `/` e `/var/log` estáveis; GC/heap normais dos outros JVM.
- Urgência (emergency-dept): fluxo normal de triagem/admissão/alta (prioridades Manchester) — sem anomalia.

## Leitura do dia (narrativa para o relatório)
Dia com **cascata de incidentes clínicos em horário diurno**: login (manhã) → laboratório (fim de manhã) → processo clínico
(início da tarde) → prescrição sem validação de dose (tarde) → portal (fim de tarde). Três problemas **continuam ativos à meia-noite**
(INC-05, INC-06, INC-07) e um deles (INC-06) tem rutura prevista **antes da manhã**. Nenhum dos 4 P1 foi detetado pela
monitorização existente.
