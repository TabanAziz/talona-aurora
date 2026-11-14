"""Machine activity from the public checks, registry, flags and record projections."""
from datetime import datetime, timezone
from urllib.parse import quote
from app.core import site


def _moment(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def machine_section(day: str, record: list[dict], checks: list[dict], machines: list[dict], flags: list[dict]):
    def on_day(value):
        at = _moment(value)
        return at is not None and site.local(at).date().isoformat() == day

    def line(key, text, entry_id):
        return {"key": key, "text": text, "source": {
            "label": "Record entry", "href": "/#record-" + quote(entry_id, safe="")}}

    lines = []
    for machine in sorted(machines, key=lambda item: item["id"]):
        identity = machine["id"]
        asked = sorted((check for check in checks if check.get("asked_by") == identity
                        and on_day(check.get("checked_at"))), key=lambda check: (check["checked_at"], check["id"]))
        entries = sorted((entry for entry in record if entry.get("actor") == identity
                          and on_day(entry.get("at")) and not (entry.get("refs") or {}).get("check")),
                         key=lambda entry: (entry["at"], entry["id"]))
        if not asked and not entries:
            continue
        stopped = [check for check in asked if check.get("allowed") == "no"]
        check_entry = next((entry["id"] for entry in record
                            if (entry.get("refs") or {}).get("check") == (asked[0]["id"] if asked else None)
                            and (entry.get("refs") or {}).get("check")), None)
        first = check_entry or (entries[0]["id"] if entries else "r-check-" + asked[0]["id"])
        label = f"{machine['name']} ({identity})" + (" [simulated]" if machine.get("simulated", True) else "")
        lines.append(line("machine-" + identity, f"{label}: {len(asked)} start checks; {len(stopped)} stopped.", first))
        for check in asked:
            blocked = sorted({reason["flag_id"] for reason in check.get("reasons", [])
                              if reason.get("blocking") and reason.get("flag_id")})
            at = _moment(check["checked_at"]).strftime("%H:%M UTC")
            outcome = {"yes": "allowed", "no": "stopped", "unknown": "unknown"}.get(check["allowed"], check["allowed"])
            suffix = " Flags: " + ", ".join(blocked) + "." if blocked else " No blocking flag recorded."
            entry_id = next((entry["id"] for entry in record if (entry.get("refs") or {}).get("check") == check["id"]),
                            "r-check-" + check["id"])
            lines.append(line("check-" + check["id"], f"{identity} at {at}: {outcome}." + suffix, entry_id))
        for entry in entries:
            refs = entry.get("refs") or {}
            at = _moment(entry["at"]).strftime("%H:%M UTC")
            if entry.get("kind") == "acknowledgement" and refs.get("sheet") and refs.get("revision"):
                text = f"{identity} confirmed {refs['sheet']} Rev {refs['revision']} at {at}."
            else:
                text = f"{identity} at {at}: {entry['title']}"
                detail = (entry.get("detail") or "").strip()
                if detail and detail != entry["title"]:
                    text += ": " + detail
                events = set(entry.get("source_event_ids") or [])
                raised = sorted({flag["id"] for flag in flags if entry.get("kind") in {"info", "change"}
                                 and any(evidence.get("event_id") in events for evidence in flag.get("evidence", []))})
                if raised:
                    text += " Flags: " + ", ".join(raised) + "."
            lines.append(line(entry["id"], text, entry["id"]))
    return {"key": "machines", "title": "Machines", "lines": lines} if lines else None
