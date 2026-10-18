"""Download full InvestorGain GMP history for every backfill IPO into data/gmp_history.json (for replays)."""
import datetime as dt
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import fetch  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
items = json.loads((ROOT / "data" / "backfill.json").read_text())["items"]
out = {}
for it in items:
    if not (it.get("slug") and it.get("id")):
        continue
    d = {"slug": it["slug"], "id": it["id"]}
    try:
        fetch.gmp(d)
    except Exception as e:  # noqa: BLE001
        print("fail", it["name"], e)
        continue
    rows = (d.get("gmp") or {}).get("all") or []
    close = dt.date.fromisoformat(it["close"]) if it.get("close") else None
    hist = []
    for r in rows:
        m = re.match(r"(\d{1,2})-([A-Z][a-z]{2})", r["when"])
        if not m or not close:
            continue
        day = dt.datetime.strptime(f"{m.group(1)} {m.group(2)} {close.year}", "%d %b %Y").date()
        hist.append({"date": day.isoformat(), "when": r["when"], "pct": r["pct"]})
    out[it["slug"]] = hist
    print(f"{it['name'][:28]:28} rows={len(hist)}")
    time.sleep(0.7)
(ROOT / "data" / "gmp_history.json").write_text(json.dumps(out, indent=1))
