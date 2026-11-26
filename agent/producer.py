"""External log producer: streams hospital.log line by line, as if systems were writing it live.

Either appends to a file (for `server.py --follow FILE`) or POSTs to the server's /api/ingest.
  python3 agent/producer.py --to-file /tmp/live.log --speed 600
  python3 agent/producer.py --to-url http://localhost:8000/api/ingest --speed 600
"""
import json, os, sys, time, urllib.request
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
a = sys.argv
speed = float(a[a.index("--speed") + 1]) if "--speed" in a else 600
to_file = a[a.index("--to-file") + 1] if "--to-file" in a else None
to_url = a[a.index("--to-url") + 1] if "--to-url" in a else None
src = a[a.index("--src") + 1] if "--src" in a else f"{ROOT}/hospital.log"
prev = None
out = open(to_file, "a", encoding="utf-8") if to_file else None
for raw in open(src, encoding="utf-8"):
    try:
        t = datetime.fromisoformat(json.loads(raw)["timestamp"].replace("Z", "+00:00"))
        if prev:
            time.sleep(max(0, (t - prev).total_seconds() / speed))
        prev = t
    except Exception:
        pass
    if out:
        out.write(raw); out.flush()
    elif to_url:
        for attempt in (1, 2):   # retry once, then skip (plan B: keep streaming)
            try:
                urllib.request.urlopen(urllib.request.Request(to_url, raw.encode(), {"Content-Type": "text/plain"}), timeout=5); break
            except Exception as e:
                if attempt == 2: print("ingest failed, line skipped:", e, file=sys.stderr)
                time.sleep(0.5)
