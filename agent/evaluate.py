"""Validate what the agent already sent against ground_truth/incidentes_esperados.json.

Checks per expected incident: detected? when? before the target time? at the right level?
Also: duplicate 'open' alerts per problem (must be 0) and PII leaks in outputs (must be 0).
Usage: python3 agent/evaluate.py   (runs the agent in batch first)
"""
import json, os, re, sys
from datetime import datetime

KEY_TO_GT = {"idp": "INC-01", "lab": "INC-02", "dbpool": "INC-03", "dose": "INC-04", "deploy-patient-portal": "INC-05",
             "heap": "INC-06", "queue": "INC-07", "pii": "INC-08", "cert": "INC-09", "disk": "INC-10", "monitor": "INC-11"}
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def gt_key(key):
    return "INC-12" if key.startswith("lock-") else KEY_TO_GT.get(key)


def evaluate(c, date="2026-11-25"):
    gt = json.load(open(f"{ROOT}/ground_truth/incidentes_esperados.json"))["incidentes"]
    found = {gt_key(k): i for k, i in c.incidents.items() if gt_key(k)}
    rows = []
    for g in gt:
        i = found.get(g["id"])
        row = {"expected": g["id"], "level_expected": g["nivel"], "summary": g["resumo"], "detected": bool(i)}
        if i:
            row.update(agent_id=i["id"], level_agent=i["level"], opened=i["opened"][11:19],
                       status=i["status"], level_ok=i["level"] == g["nivel"] or i.get("level") == g.get("nivel"))
            if g.get("detect_by"):
                row["target"] = g["detect_by"]
                row["on_time"] = i["opened"][11:19] <= g["detect_by"]
                delay = (datetime.fromisoformat(i["opened"]) - datetime.fromisoformat(f"{date}T{g['inicio']}+00:00")).total_seconds() / 60
                row["minutes_after_start"] = round(delay, 1)
        rows.append(row)
    opens = [a["alert_id"] for a in c.alerts if a["status"] == "open"]
    dup = len(opens) - len(set(opens))
    blob = json.dumps(c.alerts, ensure_ascii=False) + json.dumps(list(c.incidents.values()), ensure_ascii=False, default=str)
    pii = len(re.findall(r"nid=\d|dob=\d{4}", blob))
    extra = [i["id"] + " " + i["title"] for k, i in c.incidents.items() if not gt_key(k)]
    so_far = [r for r in rows if r["detected"]]
    return {"rows": rows, "detected": len(so_far), "expected": len(rows),
            "on_time": sum(1 for r in rows if r.get("on_time")), "with_target": sum(1 for r in rows if "target" in r and r["detected"]),
            "duplicates": dup, "pii_in_outputs": pii, "unexpected_incidents": extra}


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import commander
    c, _ = commander.run(f"{ROOT}/hospital.log")
    r = evaluate(c)
    for row in r["rows"]:
        print(f"{row['expected']} {row['level_expected']} detected={row['detected']} agent={row.get('agent_id')} {row.get('level_agent')} "
              f"opened={row.get('opened')} target={row.get('target')} on_time={row.get('on_time')}")
    print(f"detected {r['detected']}/{r['expected']} | on time {r['on_time']}/{r['with_target']} | duplicates {r['duplicates']} | "
          f"PII in outputs {r['pii_in_outputs']} | unexpected {r['unexpected_incidents']}")
    ok = r["detected"] == r["expected"] and r["on_time"] == r["with_target"] and r["duplicates"] == 0 and r["pii_in_outputs"] == 0
    sys.exit(0 if ok else 1)
