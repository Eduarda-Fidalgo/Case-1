# End-of-Day Incident Report - 2026-11-25

Lines analysed: 6874 | invalid: 0 | alerts emitted: 14 | incidents: 12

## Action required before tomorrow morning
- **[P2] Memory leak - scheduling heap 63.3%, out-of-memory expected ~26/11 01:54** - Heap dump + controlled restart in a low-traffic window before ETA; fix the leak.
- **[P2] Admissions events backing up - queue at 46** - Scale consumers / investigate consumer throughput.
- **[P2] Release 2.14.0 broke /appointments/confirm** - Roll back to 2.13.4; inform patients/front desk.
- **[P1 follow-up]** Pharmacy must review 38 prescriptions issued without dose check.
- **[P1 follow-up]** DB connection leak root cause still unknown - pool was only reinitialised.

## Incidents by urgency

| ID | Level | Opened | Status | Service | Incident | Why |
|---|---|---|---|---|---|---|
| INC-03 | P1 | 07:58 | resolved 08:25 | auth | Staff cannot log in - identity provider idp-02:8443 unreachable | Repeated connection timeouts to the IdP and every login failing with UPSTREAM_TIMEOUT. Clinicians are locked out of all systems (shift change). |
| INC-04 | P1 | 10:30 | resolved 15:21 | clinical-record-db | Database connection leak - pool at 75% and rising | Pool usage rises steadily (~1 pt / 10 min) during the day: a connection leak. At this pace the pool is exhausted in a few hours and the electronic health record stops. |
| INC-05 | P1 | 11:02 | resolved 13:14 | lab-interface | No lab results for 15 min | Normal daytime rate is ~1 result/min. Results (troponin, INR, CBC) are not reaching clinicians. The HL7 connection to the analyser gateway was closed at 10:47 (logged only as DEBUG). Hourly stats still show 0 errors. |
| INC-10 | P1 | 15:02 | resolved 16:35 | prescriptions | Prescriptions issued WITHOUT dose checking | dose_check='bypass' (never seen before today). Risk of medication error. Pharmacy stock sync is failing at the same time (1 partial syncs). |
| INC-06 | P2 | 11:19 | resolved 11:53 | clinical-record | Patient personal data written to logs (GDPR) | Full name, civil ID and date of birth appear in log field 'ctx' after a config reload to verbose logging. Logs may already be replicated. |
| INC-08 | P2 | 14:00 | active at end of day | scheduling | Memory leak - scheduling heap 63.3%, out-of-memory expected ~26/11 01:54 | Heap grows 2.6 pts/h and accelerating, never recovered by GC; projected exhaustion in 11.9 h. Other JVMs are stable at 41-49%. |
| INC-09 | P2 | 14:45 | active at end of day | admissions | Admissions events backing up - queue at 46 | Queue grew in 10/12 intervals over the last hour (produced > consumed). It will not drain on its own; admission/bed events are delayed. |
| INC-11 | P2 | 17:30 | active at end of day | patient-portal | Release 2.14.0 broke /appointments/confirm | New error 'NullPointerException in SlotMapper' appeared only after deploy 2.13.4 -> 2.14.0 at 16:40 and keeps recurring. Load balancer health checks stay green. |
| INC-01 | P3 | 06:00 | open | auth | Certificate 'saml-signing' expires 2026-12-15 (20 days) | If the SAML signing certificate expires, ALL SSO logins fail. |
| INC-02 | P3 | 06:00 | open | system-monitor | Archive disk /var/lib/archive above 85% | Monitor projects full in 14 days (re-checked against real trend at end of day). Real trend: +2.05 pts/day from 88.0% => full in ~5.9 days (monitor said 14). |
| INC-07 | P3 | 13:41 | open | auth | Account u0814 locked after 8 failed attempts | Isolated burst of bad passwords on one account (no spraying pattern). |
| INC-12 | P3 | 00:00 | open | monitoring-agent | Existing monitoring is blind | Health sweeps reported 0 failed checks 34 times while a P1 incident was open; hourly stats report 0 errors during outages; critical events logged as DEBUG/INFO. |

## Suppressed noise (not alerted)

- cache miss/evict DEBUG: 270
- audit DEBUG dumps (look like stack traces): 72
- deprecated endpoint calls (radiology-pacs /v1): 48
- individual bad passwords: 34
- broker consumer reconnects (<2 s): 32
- slow report query q_monthly_occupancy: 22
- LB health check during rolling deploy: 10
- backup temp lock vanished (ERROR): 1

## Affected patients (pseudonymised refs only)

Prescriptions without dose check: PR-91997, PR-76805, PR-29719, PR-66956, PR-70408, PR-37282, PR-42977, PR-64419, PR-31177, PR-44472, PR-60148, PR-32773, PR-66773, PR-44307, PR-83240, PR-65184, PR-95521, PR-62106, PR-35445, PR-20320, PR-24781, PR-70773, PR-80267, PR-97103, PR-45149, PR-49681, PR-45993, PR-46493, PR-53251, PR-56304, PR-12558, PR-37132, PR-46798, PR-40672, PR-30302, PR-59480, PR-64104, PR-74175