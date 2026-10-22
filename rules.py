"""The last-day decision rule, shared by render.py (display) and results.py (locking).

Stages, by the IPO's last day (close date) in IST:
  watching     before the last day: no call, only a lean
  provisional  last day before LOCK_HOUR: the call as of now
  final        last day from LOCK_HOUR: locked into data/results.json by results.py
Call = APPLY only if: Anant's latest grade is A (or A? = clearly positive, no letter),
GMP on the last day >= gate (the lowest source if sources differ by >= 5 points),
and institutions (QIB) have bid at least 1x. A notes "override" can only force SKIP.
The fall from the GMP peak is shown as a warning, not a gate (replay on past IPOs: it never changed a call).
"""
import datetime as dt
import re

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
LOCK_HOUR = 14
SPREAD_PTS = 5
PEAK_WARN_PCT = 30


def stage(close_iso, now):
    close = dt.date.fromisoformat(close_iso)
    if now.date() < close:
        return "watching"
    if now.date() == close and now.hour < LOCK_HOUR:
        return "provisional"
    if now.date() == close and now.hour < 17:
        return "final"
    return "closed"


def gmp_sources(i):
    out = []
    g = (i.get("gmp") or {}).get("latest") or {}
    main = (i.get("gmp") or {}).get("source", "InvestorGain")
    if g.get("pct") is not None:
        out.append((main, g["pct"]))
    if main != "IPOWatch" and (i.get("gmp_ipowatch") or {}).get("pct") is not None:
        out.append(("IPOWatch", i["gmp_ipowatch"]["pct"]))
    if (i.get("gmp_anant") or {}).get("pct") is not None:
        out.append(("Anant", i["gmp_anant"]["pct"]))
    return out


def gmp_used(i):
    """InvestorGain normally; the lowest source when they disagree by SPREAD_PTS or more."""
    src = gmp_sources(i)
    if not src:
        return None, None, 0
    spread = max(p for _, p in src) - min(p for _, p in src)
    if spread >= SPREAD_PTS:
        name, p = min(src, key=lambda s: s[1])
        return p, name, spread
    return src[0][1], src[0][0], spread


def peak_drop(i):
    """How far today's GMP sits below its highest reading so far (InvestorGain, or IPOWatch when that is down; newest first)."""
    rows = [r["pct"] for r in ((i.get("gmp") or {}).get("all") or []) if r.get("pct", 0) > 0]
    if not rows:
        return None, None
    peak = max(rows)
    return peak, (1 - rows[0] / peak) * 100 if peak else 0


def decide(i, gate, now):
    st = stage(i["close"], now) if i.get("close") else "watching"
    grade = i.get("anant") or "—"
    g, g_src, spread = gmp_used(i)
    qib = (i.get("subscription") or {}).get("qib")
    peak, drop = peak_drop(i)

    a_ok = grade in ("A", "A?") if grade not in ("—", None) else None
    g_ok = None if g is None else g >= gate
    q_ok = None if qib is None else qib >= 1
    checks = [
        ("Anant", a_ok, {"A": "Rated A", "A?": "Positive, no letter grade", "B": "Rated B", "C": "Rated C"}.get(grade, "Not covered yet")),
        ("GMP", g_ok, "No GMP yet" if g is None else
         f"{g:.1f}% {'≥' if g_ok else '<'} {gate}%" + (f" (lowest source: {g_src})" if spread >= SPREAD_PTS else "")),
        ("QIB", q_ok, "Bidding not open" if qib is None else f"{qib:.2f}× {'≥' if q_ok else '<'} 1×"),
    ]
    warn = (f"GMP is {drop:.0f}% below its peak of {peak:.1f}%" if drop is not None and drop > PEAK_WARN_PCT else None)
    override = i.get("override") or {}

    call, why = None, ""
    if st == "watching":
        if a_ok is None:
            lean = "Waiting for Anant"
        elif a_ok and g_ok:
            lean = "Leaning apply"
        else:
            lean = "Leaning skip"
        return {"stage": st, "call": None, "lean": lean, "checks": checks, "gmp": g, "warn": warn,
                "why": "Decided on the last day only."}
    if override.get("verdict") == "SKIP":
        call, why = "SKIP", override.get("reason", "Skipped on Anant's latest view.")
    elif a_ok and g_ok and q_ok:
        call, why = "APPLY", "Passes all three checks."
    elif a_ok and g_ok and st == "provisional" and not q_ok:
        call, why = "CONDITIONAL", "Apply if institutions (QIB) reach 1× by 2 pm."
    else:
        failed = [name for name, ok, _ in checks if not ok]
        call, why = "SKIP", "Fails: " + ", ".join(failed) + "."
    return {"stage": st, "call": call, "lean": None, "checks": checks, "gmp": g, "warn": warn, "why": why}


def parse_gmp_day(when, year):
    m = re.match(r"(\d{1,2})-([A-Z][a-z]{2})", when or "")
    return dt.datetime.strptime(f"{m.group(1)} {m.group(2)} {year}", "%d %b %Y").date() if m else None
