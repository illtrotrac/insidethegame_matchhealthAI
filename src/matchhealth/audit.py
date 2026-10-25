"""Full-time pipeline audit: did every stage run for every moment?

Reads only shared state (Cosmos in Azure), so it checks what was actually
recorded, not what the code meant to do. A confirmed moment is complete when
its trigger, Spotter verdict, overlay (from the Analyst + Producer, or a
recorded recovery) and persona variants are all stored, and it was
published. Anything else is listed as an issue.

    python -m matchhealth.audit <match_id>     # audit a stored match in Cosmos
"""

from __future__ import annotations

import sys

EXPECTED_NARRATIVES = ("n-pre-match", "n-15", "n-halftime", "n-60", "n-recap")
EXPECTED_BRIEFS = ("n-brief-15", "n-brief-halftime", "n-brief-60", "n-brief-fulltime")


def audit_match(store, published: set[str] | None = None) -> dict:
    moments = sorted(store.moments(), key=lambda m: m["trigger"]["t"])
    issues: list[str] = []
    confirmed = complete = recoveries = 0
    for m in moments:
        mid = m["id"]
        if "spotter" not in m:
            issues.append(f"{mid}: no Spotter verdict")
            continue
        if not m["spotter"].get("confirm"):
            continue
        confirmed += 1
        recovery = m.get("recovery") or {}
        recoveries += bool(recovery)
        missing = [s for s in ("producer", "personaliser") if s not in m]
        if "analyst" not in m and not recovery:
            missing.append("analyst (and no recovery recorded)")
        if published is not None and mid not in published:
            missing.append("published")
        if missing:
            issues.append(f"{mid}: missing {', '.join(missing)}")
        else:
            complete += 1

    ungrounded = sum(len((m.get("grounding") or {}).get("rejected", [])) for m in moments)
    narratives = {}
    for doc in (*EXPECTED_NARRATIVES, *EXPECTED_BRIEFS):
        d = store.get(doc)
        narratives[doc] = "written" if "narrator" in d else "missing"
        if "narrator" not in d:
            issues.append(f"{doc}: not written")
        ungrounded += len((d.get("grounding") or {}).get("rejected", []))
        recoveries += bool(d.get("recovery"))
    return {"moments": len(moments), "confirmed": confirmed, "complete": complete,
            "recoveries": recoveries, "ungrounded_rejected": ungrounded,
            "narratives": narratives, "issues": issues, "passed": not issues}


def main() -> None:  # pragma: no cover - needs Cosmos
    from dotenv import load_dotenv

    from matchhealth.shared.state import CosmosStore

    load_dotenv()
    report = audit_match(CosmosStore(sys.argv[1]))
    print({k: v for k, v in report.items() if k != "narratives"})
    for issue in report["issues"]:
        print("  -", issue)


if __name__ == "__main__":
    main()
