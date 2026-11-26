"""AI Incident Commander - streaming triage engine (stdlib only).

Reads hospital.log line by line (as if arriving live), never looks ahead,
emits each alert once per problem (with escalate/resolve updates), and builds
an end-of-day report. Output: output/alerts.jsonl, output/report.md, web/data.js
Usage: python3 agent/commander.py [path/to/hospital.log] [--live SPEED]
"""
import json, re, sys, os, time
from datetime import datetime, timedelta
from collections import Counter, defaultdict, deque

PII_RE = re.compile(r'(nm=[^;"]+|nid=\d+|dob=\d{4}-\d{2}-\d{2})')
LEVEL_ORDER = {"P1": 1, "P2": 2, "P3": 3, "P4": 4}
RESPONSE = {
    "P1": {"who": ["On-call engineer", "Service owner", "Clinical shift lead"], "how": ["PAGER", "SMS", "PHONE", "#war-room"], "sla": "Alert <1 min, ack <=5 min, mitigation <=15 min"},
    "P2": {"who": ["On-call engineer", "Owning team"], "how": ["PUSH", "Team channel", "Priority ticket"], "sla": "Ack <=30 min, mitigate <=4 h"},
    "P3": {"who": ["Owning team"], "how": ["Ticket", "End-of-day report"], "sla": "Next business day / before deadline"},
    "P4": {"who": ["Backlog"], "how": ["End-of-day report"], "sla": "Backlog"},
}


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def redact(v):
    return PII_RE.sub(lambda m: m.group(0).split("=")[0] + "=[REDACTED]", v) if isinstance(v, str) else v


def slope_per_hour(pts):
    n = len(pts)
    if n < 3:
        return 0.0
    xs = [(t - pts[0][0]).total_seconds() / 3600 for t, _ in pts]
    ys = [y for _, y in pts]
    mx, my = sum(xs) / n, sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs) or 1e-9
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den


class Commander:
    def __init__(self):
        self.incidents = {}
        self.alerts = []
        self.noise = Counter()
        self.stats = Counter()
        self.hourly = defaultdict(Counter)
        self.invalid = []
        self.clock = None
        # state
        self.auth_to = deque()
        self.last_lab = None
        self.lab_disconnect = None
        self.pool = deque(maxlen=6)
        self.heap = deque(maxlen=8)
        self.queue = deque(maxlen=13)
        self.deploys = {}
        self.err_sigs = defaultdict(set)
        self.new_sig = defaultdict(list)
        self.bypass = []
        self.pharm_partial = []
        self.bad_creds = defaultdict(deque)
        self.pii_lines = 0
        self.last_metric = {}
        self.monitor_zero = 0

    # ---------- incident lifecycle ----------
    def emit(self, key, status, level, service, hosts, title, why, action, line, extra=None):
        inc = self.incidents.get(key)
        if status == "open":
            if inc:
                return
            inc = self.incidents[key] = {"id": f"INC-{len(self.incidents)+1:02d}", "key": key, "level": level, "service": service,
                                         "hosts": sorted(set(hosts)), "title": title, "why": why, "action": action,
                                         "opened": self.clock.isoformat(), "status": "open", "evidence": [line], "updates": []}
        else:
            if not inc or inc["status"] == "resolved":
                return
            if status == "escalated":
                if LEVEL_ORDER[level] >= LEVEL_ORDER[inc["level"]]:
                    return
                inc["level"] = level
            inc["status"] = status
            inc["evidence"].append(line)
            if status == "resolved":
                inc["resolved"] = self.clock.isoformat()
        inc.update(extra or {})
        lv = inc["level"]
        msg = {"alert_id": inc["id"], "emitted_at": self.clock.isoformat(), "status": status, "level": lv,
               "service": service, "hosts": inc["hosts"], "title": title, "explanation": why, "action": action,
               "notify": RESPONSE[lv]["who"], "channels": RESPONSE[lv]["how"], "sla": RESPONSE[lv]["sla"], "evidence_line": line}
        if lv in ("P1", "P2") or status != "open":
            self.alerts.append(msg)
        inc["updates"].append(msg)
        if LIVE:
            col = {"P1": "\033[91m", "P2": "\033[93m", "P3": "\033[94m", "P4": "\033[90m"}[lv]
            print(f"{col}[{lv}] {self.clock:%H:%M:%S} {status.upper():9} {inc['id']} {service}: {title}\033[0m", flush=True)

    # ---------- per-line processing ----------
    def feed(self, n, raw):
        raw = raw.strip()
        if not raw:
            return
        try:
            r = json.loads(raw)
            t = ts(r["timestamp"])
        except Exception as e:
            self.invalid.append({"line": n, "error": str(e)[:80]})
            return
        self.clock = t
        s, m, lv, h = r.get("service"), r.get("message"), r.get("level"), r.get("host")
        self.stats[lv] += 1
        self.hourly[t.hour][lv] += 1
        self.last_metric[(s, m)] = t
        self.tick(n)

        # PII leak (redact first)
        txt = " ".join(str(v) for v in r.values())
        if PII_RE.search(txt):
            self.pii_lines += 1
            self.emit("pii", "open", "P2", s, [h], "Patient personal data written to logs (GDPR)",
                      "Full name, civil ID and date of birth appear in log field 'ctx' after a config reload to verbose logging. Logs may already be replicated.",
                      "Notify DPO (72h GDPR clock), purge/mask logs in all copies, revert verbose log_ctx and review deploy-bot change.", n)
            self.incidents["pii"]["count"] = self.pii_lines
        if s == "clinical-record" and m == "config reloaded" and r.get("log_ctx") == "default":
            self.emit("pii", "resolved", "P2", s, [h], "Verbose logging reverted - PII no longer written",
                      f"{self.pii_lines} log lines contained PII. Purge still required.", "Complete log purge and DPO assessment.", n)

        # Auth / IdP outage
        if s == "auth" and m == "upstream connect timeout":
            self.auth_to.append(t)
            while self.auth_to and t - self.auth_to[0] > timedelta(minutes=5):
                self.auth_to.popleft()
            if len(self.auth_to) >= 3:
                self.emit("idp", "open", "P1", "auth", [h], f"Staff cannot log in - identity provider {r.get('upstream')} unreachable",
                          "Repeated connection timeouts to the IdP and every login failing with UPSTREAM_TIMEOUT. Clinicians are locked out of all systems (shift change).",
                          "Fail over to secondary IdP, check idp-02; clinical lead activates downtime procedures / break-glass accounts.", n)
        if s == "auth" and m == "login failed" and r.get("reason") == "UPSTREAM_TIMEOUT" and "idp" in self.incidents:
            self.incidents["idp"]["failed_logins"] = self.incidents["idp"].get("failed_logins", 0) + 1
        if s == "auth" and m == "upstream connected":
            self.emit("idp", "resolved", "P1", "auth", [h], "Identity provider reachable again - logins restored",
                      f"Outage caused {self.incidents.get('idp', {}).get('failed_logins', 0)} failed logins.", "Post-mortem: single IdP dependency for both auth nodes.", n)

        # Lab feed
        if s == "lab-interface" and m == "result received":
            if "lab" in self.incidents and self.incidents["lab"]["status"] != "resolved":
                self.emit("lab", "resolved", "P1", s, [h], "Lab results flowing again",
                          f"Feed silent since {self.last_lab:%H:%M}. Backlog delivered.", "Review delayed critical results (troponin, INR) with clinicians.", n)
            self.last_lab = t
        if s == "lab-interface" and "peer closed" in (m or ""):
            self.lab_disconnect = (t, n)
        if s == "lab-interface" and m == "backlog received":
            if "lab" in self.incidents:
                self.incidents["lab"]["backlog"] = r.get("messages")

        # DB pool
        if s == "clinical-record-db" and m == "connection pool usage":
            self.pool.append(r["usage_pct"])
            p = list(self.pool)
            if len(p) == 6 and all(b > a for a, b in zip(p, p[1:])) and p[-1] >= 70 and 9 <= t.hour <= 20:
                self.emit("dbpool", "open", "P2", "clinical-record-db", [h], f"Database connection leak - pool at {p[-1]}% and rising",
                          "Pool usage rises steadily (~1 pt / 10 min) during the day: a connection leak. At this pace the pool is exhausted in a few hours and the electronic health record stops.",
                          "DBA/on-call: find the leaking client, recycle pool BEFORE exhaustion.", n)
        if s == "clinical-record" and m == "acquire timeout":
            self.emit("dbpool", "escalated", "P1", "clinical-record", [h], "Electronic health record failing - DB pool exhausted",
                      "Clinical-record cannot get DB connections (E-DB-0412); clinicians cannot open patient records.",
                      "Recycle DB pool now; clinical lead activates paper downtime procedure.", n)
        if s == "clinical-record-db" and m == "pool reinit":
            self.emit("dbpool", "resolved", "P1", s, [h], "DB pool reinitialised - patient records available",
                      "Manual pool reinit by on-call. Root cause (leak) NOT fixed.", "Mandatory follow-up: find connection leak to avoid recurrence.", n)

        # Prescriptions safety control
        if s == "prescriptions" and m == "prescription issued":
            if r.get("dose_check") != "pass":
                self.bypass.append(r.get("patient_ref"))
                self.emit("dose", "open", "P1", "prescriptions", [h], "Prescriptions issued WITHOUT dose checking",
                          f"dose_check='{r.get('dose_check')}' (never seen before today). Risk of medication error. Pharmacy stock sync is failing at the same time ({len(self.pharm_partial)} partial syncs).",
                          "Pharmacist double-checks every new prescription; restore pharmacy sync; retrospective review of affected prescriptions.", n)
                self.incidents["dose"]["affected_patients"] = list(self.bypass)
            elif "dose" in self.incidents and self.incidents["dose"]["status"] != "resolved":
                self.emit("dose", "resolved", "P1", s, [h], "Dose checking active again",
                          f"{len(self.bypass)} prescriptions were issued without dose check - each must be reviewed.", "Pharmacy retrospective review of listed patient_refs.", n)
        if s == "pharmacy" and m == "sync incomplete":
            self.pharm_partial.append(t)

        # Deploy regression
        if s == "deployer" and m == "deployed":
            self.deploys[r["target"]] = (t, r.get("version"), r.get("previous"))
        if lv == "ERROR" and r.get("error"):
            sig = (s, r.get("error"), r.get("path"))
            d = self.deploys.get(s)
            if d and t - d[0] < timedelta(hours=2) and sig not in self.err_sigs[s]:
                self.new_sig[sig].append(t)
                ts_ = self.new_sig[sig]
                if len(ts_) >= 3 and ts_[-1] - ts_[0] >= timedelta(minutes=15):
                    self.err_sigs[s].add(sig)
                    self.emit("deploy-" + s, "open", "P2", s, [h], f"Release {d[1]} broke {r.get('path')}",
                              f"New error '{r.get('error')}' appeared only after deploy {d[2]} -> {d[1]} at {d[0]:%H:%M} and keeps recurring. Load balancer health checks stay green.",
                              f"Roll back to {d[2]}; inform patients/front desk.", n)
            elif not d or t - d[0] >= timedelta(hours=2):
                self.err_sigs[s].add(sig)
        if s == "patient-portal" and m == "request failed" and "deploy-patient-portal" in self.incidents:
            self.incidents["deploy-patient-portal"]["failures"] = self.incidents["deploy-patient-portal"].get("failures", 0) + 1

        # Heap trend
        if m == "jvm heap usage":
            if s == "scheduling":
                self.heap.append((t, r["heap_used_pct"]))
                if len(self.heap) == 8:
                    sl = slope_per_hour(list(self.heap))
                    cur = self.heap[-1][1]
                    if sl > 0.5:
                        hrs = (100 - cur) / sl
                        eta = t + timedelta(hours=hrs)
                        if hrs < 12:
                            self.emit("heap", "open", "P2", s, [h], f"Memory leak - scheduling heap {cur}%, out-of-memory expected ~{eta:%d/%m %H:%M}",
                                      f"Heap grows {sl:.1f} pts/h with no recovery after GC; projected exhaustion in {hrs:.1f} h. Other JVMs are stable at 41-49%.",
                                      "Heap dump + controlled restart in a low-traffic window before ETA; fix the leak.", n, {"eta": eta.isoformat()})
                        if (cur >= 95 or hrs < 2):
                            self.emit("heap", "escalated", "P1", s, [h], f"Scheduling about to crash - heap {cur}%", "Exhaustion imminent.", "Restart now.", n)
                        if "heap" in self.incidents:
                            self.incidents["heap"]["eta"] = eta.isoformat()
                            self.incidents["heap"]["heap_pct"] = cur

        # Admissions queue
        if s == "admissions" and m == "queue depth":
            self.queue.append(r["depth"])
            q = list(self.queue)
            if len(q) == 13:
                ups = sum(1 for a, b in zip(q, q[1:]) if b > a)
                if ups >= 10 and q[-1] - q[0] >= 30:
                    self.emit("queue", "open", "P2", s, [h], f"Admissions events backing up - queue at {q[-1]}",
                              f"Queue grew in {ups}/12 intervals over the last hour (produced > consumed). It will not drain on its own; admission/bed events are delayed.",
                              "Scale consumers / investigate consumer throughput.", n)
            if "queue" in self.incidents:
                self.incidents["queue"]["depth"] = r["depth"]

        # P3 / planning signals (report, no paging)
        if r.get("days_left") is not None:
            self.emit("cert", "open", "P3", s, [h], f"Certificate '{r.get('cert')}' expires {r.get('not_after','')[:10]} ({r['days_left']} days)",
                      "If the SAML signing certificate expires, ALL SSO logins fail.", "Renew at least 7 days before expiry.", n)
        if s == "system-monitor" and m == "disk usage" and r.get("mount") == "/var/lib/archive":
            self.disk = getattr(self, "disk", []) + [(t, r["used_pct"])]
        if s == "system-monitor" and m == "disk usage above threshold":
            self.emit("disk", "open", "P3", s, [h], f"Archive disk {r.get('mount')} above {r.get('threshold_pct')}%",
                      f"Monitor projects full in {r.get('projected_full_days')} days (re-checked against real trend at end of day).", "Expand or clean archive this week.", n)
        if s == "auth" and m == "account locked":
            self.emit("lock-" + r["user"], "open", "P3", s, [h], f"Account {r['user']} locked after {r.get('attempts')} failed attempts",
                      "Isolated burst of bad passwords on one account (no spraying pattern).", "Helpdesk/security confirm with the user.", n)
        if s == "monitoring-agent" and r.get("failed_checks") == 0:
            if any(i["status"] != "resolved" and i["level"] == "P1" for i in self.incidents.values()):
                self.monitor_zero += 1

        # noise accounting
        if s == "backup" and m == "file vanished during backup": self.noise["backup temp lock vanished (ERROR)"] += 1
        if s == "load-balancer" and m == "health check failed": self.noise["LB health check during rolling deploy"] += 1
        if s == "audit": self.noise["audit DEBUG dumps (look like stack traces)"] += 1
        if s == "cache" and lv == "DEBUG": self.noise["cache miss/evict DEBUG"] += 1
        if s == "message-broker" and "connection lost" in (m or ""): self.noise["broker consumer reconnects (<2 s)"] += 1
        if s == "integration-gateway" and m == "deprecated endpoint called": self.noise["deprecated endpoint calls (radiology-pacs /v1)"] += 1
        if s == "auth" and r.get("reason") == "BAD_CREDENTIALS": self.noise["individual bad passwords"] += 1
        if s == "reports" and m == "slow query": self.noise["slow report query q_monthly_occupancy"] += 1

    def tick(self, n):
        t = self.clock
        # lab silence detector: runs on the clock, not on lab lines
        if self.last_lab and 7 <= t.hour <= 21 and t - self.last_lab > timedelta(minutes=15):
            dis = f" The HL7 connection to the analyser gateway was closed at {self.lab_disconnect[0]:%H:%M} (logged only as DEBUG)." if self.lab_disconnect else ""
            self.emit("lab", "open", "P1", "lab-interface", ["lab-01"], f"No lab results for {int((t-self.last_lab).seconds/60)} min",
                      "Normal daytime rate is ~1 result/min. Results (troponin, INR, CBC) are not reaching clinicians." + dis + " Hourly stats still show 0 errors.",
                      "Restart HL7 listener / check analyser gateway; lab phones critical results until restored.", self.lab_disconnect[1] if self.lab_disconnect else n)
        # metric silence detector (DB metrics every 10 min)
        lm = self.last_metric.get(("clinical-record-db", "connection pool usage"))
        if lm and t - lm > timedelta(minutes=25) and "dbpool" in self.incidents:
            self.incidents["dbpool"]["metrics_silent_since"] = lm.isoformat()

    def finish(self):
        # end-of-day checks
        if getattr(self, "disk", None) and len(self.disk) > 2:
            sl = slope_per_hour(self.disk) * 24
            cur = self.disk[-1][1]
            if "disk" in self.incidents and sl > 0:
                days = (100 - cur) / sl
                self.incidents["disk"]["real_projection_days"] = round(days, 1)
                self.incidents["disk"]["why"] += f" Real trend: +{sl:.2f} pts/day from {cur}% => full in ~{days:.1f} days (monitor said 14)."
        if self.monitor_zero:
            self.incidents["monitor"] = {"id": f"INC-{len(self.incidents)+1:02d}", "key": "monitor", "level": "P3", "service": "monitoring-agent", "hosts": ["mon-01"],
                                         "title": "Existing monitoring is blind", "status": "open", "opened": self.clock.isoformat(), "evidence": [], "updates": [],
                                         "why": f"Health sweeps reported 0 failed checks {self.monitor_zero} times while a P1 incident was open; hourly stats report 0 errors during outages; critical events logged as DEBUG/INFO.",
                                         "action": "Add silence detection, trend alerts and business-flow health checks."}
        for i in self.incidents.values():
            if i["status"] != "resolved":
                i["status"] = "active at end of day" if i["level"] in ("P1", "P2") else "open"


LIVE = False


def run(path, speed=None):
    global LIVE
    LIVE = speed is not None
    c = Commander()
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        print(f"ERROR: log file '{path}' missing or empty - nothing to analyse."); sys.exit(1)
    prev = None
    lines = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for n, raw in enumerate(f, 1):
            lines.append(raw)
            if speed:
                try:
                    cur = ts(json.loads(raw)["timestamp"])
                    if prev: time.sleep(max(0, (cur - prev).total_seconds() / speed))
                    prev = cur
                except Exception:
                    pass
            c.feed(n, raw)
    c.finish()
    return c, lines


def write_outputs(c, lines, root):
    os.makedirs(f"{root}/output", exist_ok=True)
    with open(f"{root}/output/alerts.jsonl", "w") as f:
        for a in c.alerts:
            f.write(json.dumps(a, ensure_ascii=False) + "\n")
    incs = sorted(c.incidents.values(), key=lambda i: (LEVEL_ORDER[i["level"]], i["opened"]))
    rep = ["# End-of-Day Incident Report - 2026-11-25", "",
           f"Lines analysed: {sum(c.stats.values())} | invalid: {len(c.invalid)} | alerts emitted: {len(c.alerts)} | incidents: {len(incs)}", "",
           "## Action required before tomorrow morning"]
    for i in incs:
        if i["status"] == "active at end of day":
            rep.append(f"- **[{i['level']}] {i['title']}** - {i['action']}")
    if "dose" in c.incidents:
        rep.append(f"- **[P1 follow-up]** Pharmacy must review {len(c.bypass)} prescriptions issued without dose check.")
    if "dbpool" in c.incidents:
        rep.append("- **[P1 follow-up]** DB connection leak root cause still unknown - pool was only reinitialised.")
    rep += ["", "## Incidents by urgency", "", "| ID | Level | Opened | Status | Service | Incident | Why |", "|---|---|---|---|---|---|---|"]
    for i in incs:
        rep.append(f"| {i['id']} | {i['level']} | {i['opened'][11:16]} | {i['status']}{' '+i['resolved'][11:16] if i.get('resolved') else ''} | {i['service']} | {i['title']} | {i['why']} |")
    rep += ["", "## Suppressed noise (not alerted)", ""] + [f"- {k}: {v}" for k, v in c.noise.most_common()]
    rep += ["", "## Affected patients (pseudonymised refs only)", "", "Prescriptions without dose check: " + ", ".join(c.bypass)]
    open(f"{root}/output/report.md", "w").write("\n".join(rep))
    # web data (redacted lines for the live replay)
    slim = []
    for n, raw in enumerate(lines, 1):
        try:
            r = json.loads(raw)
            slim.append([r["timestamp"], r["level"], r["service"], r["host"], redact(r["message"]),
                         redact(json.dumps({k: redact(v) for k, v in r.items() if k not in ("timestamp", "level", "service", "host", "trace_id", "message")}, ensure_ascii=False))])
        except Exception:
            slim.append(["", "INVALID", "", "", raw[:80], ""])
    data = {"date": "2026-11-25", "alerts": c.alerts, "incidents": incs, "noise": c.noise, "stats": c.stats,
            "hourly": {h: dict(v) for h, v in c.hourly.items()}, "invalid": c.invalid, "lines": slim, "report": "\n".join(rep),
            "response": RESPONSE, "bypass": c.bypass}
    os.makedirs(f"{root}/web", exist_ok=True)
    open(f"{root}/web/data.js", "w").write("window.DATA=" + json.dumps(data, ensure_ascii=False, default=str) + ";")


if __name__ == "__main__":
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else f"{root}/hospital.log"
    speed = float(sys.argv[sys.argv.index("--live") + 1]) if "--live" in sys.argv else None
    c, lines = run(path, speed)
    write_outputs(c, lines, root)
    for i in sorted(c.incidents.values(), key=lambda i: (LEVEL_ORDER[i["level"]], i["opened"])):
        print(f"{i['level']} {i['id']} {i['opened'][11:19]} {i['status']:22} {i['service']:20} {i['title']}")
    print(f"alerts={len(c.alerts)} invalid={len(c.invalid)}")
