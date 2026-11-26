"""Live AI Incident Commander server (stdlib only).

Real-time input, three ways (all feed the same streaming engine, line by line):
  1. replay   - replays hospital.log respecting timestamps (x speed)           [default]
  2. follow   - tails a log file that another system keeps appending to        (--follow FILE)
  3. ingest   - external systems POST JSON lines to /api/ingest                (any time)

Operators can: acknowledge sent alerts (stops re-notification), pause / resume / restart ("play again"),
change speed, validate alerts against ground truth, validate a log file, read the end-of-day report.

Run:  python3 agent/server.py [--port 8000] [--speed 600] [--follow FILE]
Open: http://localhost:8000
"""
import json, os, sys, threading, time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import commander
from evaluate import evaluate

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAX_UPLOAD = 50 * 1024 * 1024


class Engine:
    def __init__(self, path, speed, follow=None):
        self.path, self.follow = path, follow
        self.lock = threading.Lock()
        self.speed = speed
        self.gen = 0
        self.reset()

    def reset(self):
        with self.lock:
            commander.LIVE = False
            self.c = commander.Commander()
            self.c.auto_renotify = True
            self.lines = []          # redacted lines for the UI
            self.n = 0
            self.paused = False
            self.done = False
            self.error = None
            self.gen += 1
        threading.Thread(target=self._source, args=(self.gen,), daemon=True).start()

    def feed(self, raw, origin="replay"):
        raw = raw.rstrip("\n")
        if not raw.strip():
            return
        with self.lock:
            self.n += 1
            self.c.feed(self.n, raw)
            try:
                r = json.loads(raw)
                rest = {k: commander.redact(v) for k, v in r.items() if k not in ("timestamp", "level", "service", "host", "trace_id", "message")}
                self.lines.append([self.n, r.get("timestamp", ""), r.get("level", "?"), r.get("service", "?"), r.get("host", "?"),
                                   commander.redact(r.get("message", "")), json.dumps(rest, ensure_ascii=False)[:300], origin])
            except Exception as e:
                self.lines.append([self.n, "", "INVALID", "", "", f"invalid line rejected: {str(e)[:60]}", "", origin])

    def _source(self, gen):
        if self.follow:
            return self._tail(gen)
        if not os.path.exists(self.path) or os.path.getsize(self.path) == 0:
            self.error = f"Log file '{self.path}' is missing or empty."; self.done = True; return
        prev = None
        with open(self.path, encoding="utf-8", errors="replace") as f:
            for raw in f:
                while self.paused and gen == self.gen:
                    time.sleep(0.1)
                if gen != self.gen:
                    return
                try:
                    cur = commander.ts(json.loads(raw)["timestamp"])
                    if prev:
                        wait = (cur - prev).total_seconds() / max(self.speed, 1)
                        end = time.time() + wait
                        while time.time() < end and gen == self.gen:
                            time.sleep(min(0.05, end - time.time()) if end > time.time() else 0)
                    prev = cur
                except Exception:
                    pass
                if gen != self.gen:
                    return
                self.feed(raw)
        with self.lock:
            if gen == self.gen:
                self.c.finish(); self.done = True

    def _tail(self, gen):
        while not os.path.exists(self.follow):
            time.sleep(0.5)
        with open(self.follow, encoding="utf-8", errors="replace") as f:
            while gen == self.gen:
                line = f.readline()
                if line:
                    self.feed(line, "follow")
                else:
                    time.sleep(0.2)

    def state(self, since):
        with self.lock:
            c = self.c
            alerts = [dict(a, ack=c.acks.get(a["alert_id"])) for a in c.alerts]
            incs = sorted(c.incidents.values(), key=lambda i: (i["status"] == "resolved", commander.LEVEL_ORDER[i["level"]], i["opened"]))
            incs = [{k: v for k, v in dict(i, ack=c.acks.get(i["id"])).items() if k != "updates"} for i in incs]
            return {"clock": c.clock.isoformat() if c.clock else None, "n": self.n, "lines": self.lines[since:since + 400],
                    "next": min(len(self.lines), since + 400), "alerts": alerts, "incidents": incs, "noise": c.noise,
                    "stats": c.stats, "hourly": {h: dict(v) for h, v in c.hourly.items()}, "paused": self.paused, "done": self.done,
                    "speed": self.speed, "mode": "follow" if self.follow else "replay", "error": self.error, "invalid": len(c.invalid)}


def validate_text(text):
    lines = [l for l in text.split("\n") if l.strip()]
    if not lines:
        return {"ok": False, "message": "File is empty - nothing to validate."}
    bad, missing, order, prev = [], 0, 0, ""
    for i, l in enumerate(lines, 1):
        try:
            r = json.loads(l)
            if not all(k in r for k in ("timestamp", "level", "service", "message")):
                missing += 1
            if r.get("timestamp", "") < prev:
                order += 1
            prev = r.get("timestamp", prev)
        except Exception:
            bad.append(i)
    return {"ok": not bad and not missing, "lines": len(lines), "invalid_json": len(bad), "invalid_lines": bad[:20],
            "missing_fields": missing, "out_of_order": order,
            "message": "Valid log." if not bad and not missing else "Problems found - invalid lines are skipped by the agent, never block it."}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json"):
        b = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False, default=str).encode()
        self.send_response(code); self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_UPLOAD:
            raise ValueError("too large")
        return self.rfile.read(n).decode("utf-8", errors="replace")

    def do_GET(self):
        p, _, q = self.path.partition("?")
        if p in ("/", "/index.html"):
            return self.send(200, open(f"{ROOT}/web/live.html", "rb").read(), "text/html")
        if p == "/api/state":
            since = int(dict(x.split("=") for x in q.split("&") if "=" in x).get("since", 0))
            return self.send(200, E.state(since))
        if p == "/api/report":
            with E.lock:
                _, rep = commander.build_report(E.c)
            return self.send(200, {"report": rep})
        if p == "/api/evaluate":
            with E.lock:
                return self.send(200, evaluate(E.c))
        self.send(404, {"error": "not found"})

    def do_POST(self):
        p = self.path
        try:
            if p == "/api/ack":
                d = json.loads(self.body())
                with E.lock:
                    ok = E.c.ack(d.get("id"), d.get("by"), d.get("note", ""))
                return self.send(200 if ok else 404, {"ok": ok})
            if p == "/api/control":
                d = json.loads(self.body())
                a = d.get("action")
                if a == "pause": E.paused = True
                elif a == "resume": E.paused = False
                elif a == "restart":
                    if d.get("speed"): E.speed = float(d["speed"])
                    E.reset()
                elif a == "speed": E.speed = float(d.get("speed", E.speed))
                return self.send(200, {"ok": True})
            if p == "/api/ingest":
                text = self.body()
                n = 0
                for line in text.split("\n"):
                    if line.strip():
                        E.feed(line, "ingest"); n += 1
                return self.send(200, {"ok": True, "lines": n})
            if p == "/api/validate":
                return self.send(200, validate_text(self.body()))
        except ValueError as e:
            return self.send(413 if "large" in str(e) else 400, {"ok": False, "message": "File larger than 50 MB - use the CLI agent (streams line by line)." if "large" in str(e) else f"Bad request: {e}"})
        self.send(404, {"error": "not found"})


if __name__ == "__main__":
    a = sys.argv
    port = int(a[a.index("--port") + 1]) if "--port" in a else 8000
    speed = float(a[a.index("--speed") + 1]) if "--speed" in a else 600
    follow = a[a.index("--follow") + 1] if "--follow" in a else None
    E = Engine(f"{ROOT}/hospital.log", speed, follow)
    print(f"AI Incident Commander live on http://localhost:{port}  (mode={'follow '+follow if follow else 'replay x'+str(speed)})")
    ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()
