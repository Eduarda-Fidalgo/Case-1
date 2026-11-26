# 03 · Níveis de urgência e resposta

Princípio: a urgência mede-se pelo **impacto no doente e na operação clínica**, não pelo nível do log.
Cada incidente é classificado por 3 perguntas:

1. **Segurança do doente** — pode causar dano clínico (resultados que não chegam, prescrições sem validação, registo clínico indisponível)?
2. **Alcance** — afeta um serviço clínico inteiro / todos os utilizadores, ou um caso isolado?
3. **Tempo até ao dano** — está a acontecer agora, vai acontecer em horas, em dias, ou nunca?

| Nível | Nome | Critério | Quem é notificado | Como | Rapidez |
|---|---|---|---|---|---|
| **P1** | 🔴 Crítico — intervenção imediata | Risco direto para a segurança do doente **ou** serviço clínico essencial indisponível (EHR, laboratório, prescrição, login dos profissionais) **agora** | Engenheiro de piquete (on-call) + responsável do serviço + **chefe de equipa clínica de turno** (ex.: enfermeiro-chefe/diretor clínico de serviço) | Chamada/pager + SMS + canal de crise (war room) com alerta autónomo do agente | Alerta **imediato (<1 min após deteção)**; *ack* ≤ 5 min; mitigação a iniciar ≤ 15 min; atualização a cada 30 min; plano de contingência clínico (ex.: modo papel) ativado |
| **P2** | 🟠 Alto — ação nas próximas horas | Degradação com impacto em utentes/operação **ou** falha **projetada** em < 24h **ou** incidente de conformidade (RGPD) | Engenheiro de piquete + equipa dona do serviço; **DPO / Segurança** quando há dados pessoais | Notificação push + canal da equipa + ticket prioritário | Alerta imediato; *ack* ≤ 30 min; resolução/mitigação ≤ 4 h (RGPD: avaliação pelo DPO, prazo legal de 72 h para notificar a CNPD) |
| **P3** | 🟡 Médio — planear | Risco futuro com prazo em dias, falhas de observabilidade, eventos de segurança isolados | Equipa dona do serviço (ticket) | Ticket + resumo no relatório de fim de dia (sem acordar ninguém) | Tratar no próximo dia útil / dentro do prazo indicado |
| **P4** | 🔵 Baixo — informativo | Sem impacto atual, dívida técnica, transitórios já resolvidos | Equipas (backlog) | Apenas no relatório de fim de dia | Backlog |
| **—** | ⚪ Ruído | Comportamento esperado ou sem significado operacional | Ninguém | Suprimido; só contado no relatório (para afinar regras) | — |

## Regras de escalamento e desescalamento
- **Escalar** automaticamente quando o sinal piora: ex. pool BD P2 (>80 % e a subir) → **P1** ao primeiro `acquire timeout`/HTTP 500;
  heap scheduling P2 → P1 se >95 % ou pausas GC > 2 s.
- **Duração agrava**: um P2 não resolvido em 4 h é re-notificado ao nível seguinte da cadeia.
- **Horário**: P1/P2 notificam 24/7. P3/P4 nunca geram notificação noturna — vão para o relatório.
- **Resolução**: quando o sinal volta ao normal durante N minutos, o agente emite *update* "resolvido" (mesmo incidente) com duração total.
- **Uma vez por problema**: alertas repetidos do mesmo problema são agregados (contador + última ocorrência) — nunca um alerta por linha.

## Formato do alerta (breve explicação)
```
[P1] Laboratório sem resultados há 25 min (lab-interface/lab-01)
Quando: 2026-11-25 11:12 UTC (início provável 10:47)
O quê: a ligação HL7 ao lab-analyzer-gw foi fechada (log DEBUG) e não chegou nenhum resultado desde então;
       o normal a esta hora é ~1/min.
Porque importa: resultados (incl. troponina, INR) não chegam aos clínicos → decisões atrasadas.
Ação sugerida: reiniciar listener HL7 / verificar gateway do analisador; avisar serviços para contacto telefónico com o laboratório.
Notificados: on-call integração, responsável lab, chefe de equipa clínica.  Evidência: linha 2964 (trace a3735e4e)
```
