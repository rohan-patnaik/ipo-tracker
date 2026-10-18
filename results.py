"""Track record: freeze each tracked IPO's call when it closes, then fill in the listing-day outcome.

Reads data/auto.json + data/notes.json, updates data/results.json (committed; the page's track record).
Runs in the GitHub job and on the Mac. Never overwrites a frozen call.
"""
import datetime as dt
import json
import os
import re
from pathlib import Path

import fetch
import rules

ROOT = Path(__file__).resolve().parent
CFG = json.loads((ROOT / "config.json").read_text())
AUTO = json.loads((ROOT / "data" / "auto.json").read_text())
NOTES = json.loads((ROOT / "data" / "notes.json").read_text())
PATH = ROOT / "data" / "results.json"
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
NOW = dt.datetime.fromisoformat(os.environ["IPO_NOW"]) if os.environ.get("IPO_NOW") else dt.datetime.now(IST)  # IPO_NOW: tests only


def locked(close_iso):
    """The call locks at 2 pm IST on the last day."""
    return rules.stage(close_iso, NOW) in ("final", "closed")


def gmp_at_close(history, close_iso):
    """Latest InvestorGain reading on or before the close date (rows look like '19-Oct 23:37')."""
    close = dt.date.fromisoformat(close_iso)
    for r in history:  # newest first
        m = re.match(r"(\d{1,2})-([A-Z][a-z]{2})", r["when"])
        if not m:
            continue
        day = dt.datetime.strptime(f"{m.group(1)} {m.group(2)} {close.year}", "%d %b %Y").date()
        if day <= close and r["pct"]:
            return r["pct"]
    return None


def main():
    res = json.loads(PATH.read_text()) if PATH.exists() else {"items": {}}
    items = res["items"]
    changed = False
    for slug, a in AUTO["ipos"].items():
        n = NOTES["ipos"].get(slug)
        if not n or not a.get("close") or not locked(a["close"]):
            continue
        if slug not in items:  # lock the call (first run from 2 pm on the last day)
            s = a.get("subscription") or {}
            merged = {**a, **n}
            dec = rules.decide(merged, CFG["gmp_benchmark_pct"], NOW)
            items[slug] = {
                "locked_at": NOW.isoformat(timespec="minutes"), "why": dec["why"],
                "checks": [[name, ok, text] for name, ok, text in dec["checks"]], "warn": dec["warn"],
                "gmp_at_call": dec["gmp"],
                "name": a["name"], "slug": slug, "id": a["id"], "board": a["board"],
                "close": a["close"], "listing": a.get("listing"), "issue_price": a.get("price_high"),
                "anant": n.get("anant"), "call": dec["call"] if n.get("tracked", True) else n.get("verdict"),
                "tracked": n.get("tracked", True),
                "gmp_at_close": gmp_at_close(((a.get("gmp") or {}).get("all") or []), a["close"]),
                "sub_total": s.get("total"), "sub_retail": s.get("retail"),
                "listed": False, "you": n.get("you"),
            }
            changed = True
        it = items[slug]
        # last-day numbers keep settling after 5 pm; refresh them (not the call) until listing
        if not it["listed"] and rules.stage(a["close"], NOW) == "closed":
            s = a.get("subscription") or {}
            for k, v in (("sub_total", s.get("total")), ("sub_retail", s.get("retail")),
                         ("listing", a.get("listing"))):
                if v is not None and it.get(k) != v:
                    it[k] = v
                    changed = True
            g = gmp_at_close(((a.get("gmp") or {}).get("all") or []), a["close"])
            if g is not None and it.get("gmp_at_close") != g:
                it["gmp_at_close"] = g
                changed = True
    # fill outcomes for anything listed (also IPOs that have left the calendar window)
    for slug, it in items.items():
        if it["listed"] or not it.get("listing") or dt.date.fromisoformat(it["listing"]) > NOW.date():
            continue
        try:
            d = {"slug": slug, "id": it["id"]}
            fetch.ipo_details(d)
            ld = d.get("listing_day")
        except Exception:  # noqa: BLE001
            ld = None
        if ld and ld.get("close"):
            it.update({"listed": True, "list_open_pct": ld["open_pct"], "list_close_pct": ld["close_pct"],
                       "list_high_pct": round((ld["high"] / ld["issue"] - 1) * 100, 2) if ld.get("high") else None,
                       "issue_price": ld["issue"]})
            changed = True
    # your own applications are recorded in notes.json ("you": {...}); mirror them
    for slug, it in items.items():
        you = (NOTES["ipos"].get(slug) or {}).get("you")
        if you and it.get("you") != you:
            it["you"] = you
            changed = True
    if changed or not PATH.exists():
        res["updated_at"] = NOW.isoformat(timespec="minutes")
        PATH.write_text(json.dumps(res, indent=1, ensure_ascii=False))
        print("results.json updated")
    else:
        print("results.json unchanged")


if __name__ == "__main__":
    main()
