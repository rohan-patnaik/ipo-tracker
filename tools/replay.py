"""Replay last-day rules on past IPOs that have full GMP history."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
items = {i["slug"]: i for i in json.loads((ROOT / "data/backfill.json").read_text())["items"] if i.get("slug")}
hist = json.loads((ROOT / "data/gmp_history.json").read_text())
GATE = 15

rows = []
for slug, h in hist.items():
    it = items[slug]
    if not it.get("listed") or it.get("list_close_pct") is None:
        continue
    pre = [r["pct"] for r in h if r["date"] <= it["close"] and r["pct"] > 0]
    if not pre:
        continue
    last, peak = pre[0], max(pre)  # newest first
    rows.append(dict(name=it["name"], anant=it["anant"], last=last, peak=peak, drop=(1 - last / peak) * 100 if peak else 0,
                     close=it["list_close_pct"], open=it["list_open_pct"]))

def summ(label, sel):
    if not sel:
        print(f"{label:46} n=0"); return
    c = [r["close"] for r in sel]
    print(f"{label:46} n={len(sel):2}  avg close {sum(c)/len(c):+6.1f}%  up {100*sum(x>0 for x in c)/len(c):3.0f}%  worst {min(c):+6.1f}%")

print(f"{'IPO':28} {'Anant':5} {'last':>6} {'peak':>6} {'drop':>6} {'listclose':>9}")
for r in sorted(rows, key=lambda r: -r["drop"]):
    print(f"{r['name'][:28]:28} {r['anant']:5} {r['last']:6.1f} {r['peak']:6.1f} {r['drop']:5.0f}% {r['close']:+8.1f}%")
print()
old = [r for r in rows if r["anant"] == "A" and r["last"] >= GATE]
summ("OLD: A + last-day GMP >= 15%", old)
for k in (20, 30, 40):
    summ(f"NEW: + no more than {k}% below peak", [r for r in old if r["drop"] <= k])
    summ(f"     ...the ones it would drop", [r for r in old if r["drop"] > k])
print()
anyg = [r for r in rows if r["last"] >= GATE]
summ("GMP-only (any grade) last >= 15%", anyg)
for k in (20, 30, 40):
    summ(f"GMP-only + no more than {k}% below peak", [r for r in anyg if r["drop"] <= k])
    summ(f"     ...dropped", [r for r in anyg if r["drop"] > k])
summ("Anant A but last-day GMP < 15%", [r for r in rows if r["anant"] == "A" and r["last"] < GATE])
