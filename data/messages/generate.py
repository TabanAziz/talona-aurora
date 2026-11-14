"""Writes the message scenario: events.json, voice_texts.json and the source files in their real formats.

  python data/messages/generate.py           write everything
  python data/messages/generate.py --check   fail when the committed files differ from a fresh run

Standard library only. The output is identical on every run: fixed times, fixed ids, fixed MIME boundaries.
"""
import csv
import io
import json
import sys
from datetime import datetime, timedelta, timezone
from email import policy
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import script

HERE = Path(__file__).resolve().parent
YEAR = 2026
MAILBOX = "Maple Court project <site@maplecourt.example>"
CHAT_ID = -1001234567890
UPDATE_ID_BASE = 910000
MESSAGE_ID_BASE = 4200


def when(text: str) -> datetime:
    return datetime.strptime(f"{YEAR}-{text}", "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)


def iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def placeholder_pdf(title: str) -> bytes:
    """A one page PDF that only names the sheet. The real sheets are in data/drawings."""
    text = f"{title} (placeholder attachment, demo data)".replace("(", "[").replace(")", "]")
    stream = f"BT /F1 18 Tf 40 100 Td ({text}) Tj ET".encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 420 160] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return out


def build_events() -> list[dict]:
    """Every delivery in received order. A redelivery repeats the event id with a later received_at."""
    rows = []
    # The confirmations were added later and are not counted in `position`, so every other delay stays as it was.
    position = -1
    for index, (event_id, sent_text, channel, sender, subject, text, options) in enumerate(script.EVENTS):
        sent = when(sent_text)
        if not options.get("confirms") and not options.get("historical_rework"):
            position += 1
        if event_id:
            _, delay = script.DEMO[event_id]
        elif "received" in options:
            delay = int((when(options["received"]) - sent).total_seconds())
        else:
            delay = {"telegram": 2 + position % 3, "email": 20 + position % 5 * 5, "schedule": 0}[channel]
        attachments = []
        if options.get("audio"):
            name = "voice-note.ogg" if event_id else None
            attachments.append({"kind": "audio", "name": name, "url": None, "media_type": "audio/ogg"})
        if options.get("pdf"):
            attachments.append({
                "kind": "pdf", "name": options["pdf"], "url": options.get("pdf_url"), "media_type": "application/pdf",
            })
        rows.append({
            "key": index, "id": event_id, "channel": channel, "sent": sent, "delay": delay, "sender": sender,
            "subject": subject, "text": text, "attachments": attachments, "options": options,
        })

    next_number = 9
    for row in sorted(rows, key=lambda r: r["sent"] + timedelta(seconds=r["delay"])):
        if row["id"] is None:
            row["id"] = f"e{next_number:02d}"
            next_number += 1
    for row in rows:
        for attachment in row["attachments"]:
            if attachment["name"] is None:
                attachment["name"] = f"voice-{row['id']}.ogg"

    deliveries = []
    for row in rows:
        received = row["sent"] + timedelta(seconds=row["delay"])
        event = {
            "id": row["id"],
            "channel": row["channel"],
            "sent_at": iso(row["sent"]),
            "received_at": iso(received),
            "sender": row["sender"],
            "sender_role": script.PEOPLE[row["sender"]],
            "thread": script.THREAD if row["channel"] == "telegram" else None,
            "subject": row["subject"],
            "text": row["text"],
            "transcript": None,
            "attachments": row["attachments"],
        }
        deliveries.append((received, row["key"], 0, event, row))
        again = row["options"].get("redelivery")
        if again:
            second = dict(event, received_at=iso(received + timedelta(seconds=again)))
            deliveries.append((received + timedelta(seconds=again), row["key"], 1, second, row))
    deliveries.sort(key=lambda d: d[:3])
    return [(event, row, order) for _, _, order, event, row in deliveries]


def email_bytes(event: dict, row: dict, order: int) -> bytes:
    sender = event["sender"]
    address = script.EMAIL_ADDRESSES[sender]
    sent = datetime.strptime(event["sent_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    received = datetime.strptime(event["received_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    message = EmailMessage(policy=policy.SMTP)
    message["Received"] = f"by mx.maplecourt.example with SMTP id {event['id']}-{order}; {format_datetime(received)}"
    message["From"] = f"{sender} <{address}>"
    message["To"] = MAILBOX
    message["Subject"] = event["subject"]
    message["Date"] = format_datetime(sent)
    message["Message-ID"] = f"<{event['id']}@mail.maplecourt.example>"
    message.set_content(event["text"] + "\n")
    for attachment in event["attachments"]:
        message.add_attachment(
            placeholder_pdf(Path(attachment["name"]).stem),
            maintype="application", subtype="pdf", filename=attachment["name"],
        )
    if message.is_multipart():
        message.set_boundary(f"=====aurora-{event['id']}=====")
    return message.as_bytes()


def telegram_update(event: dict, number: int) -> dict:
    first, _, last = event["sender"].partition(" ")
    sent = datetime.strptime(event["sent_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    message = {
        "message_id": MESSAGE_ID_BASE + number,
        "from": {
            "id": 7000000 + sorted(script.PEOPLE).index(event["sender"]),
            "is_bot": False,
            "first_name": first,
            **({"last_name": last} if last else {}),
            "language_code": "en",
        },
        "chat": {"id": CHAT_ID, "title": script.THREAD, "type": "supergroup"},
        "date": int(sent.timestamp()),
    }
    if event["attachments"]:
        message["voice"] = {
            "duration": 6 + number % 5,
            "mime_type": "audio/ogg",
            "file_id": f"AwACAgQAAyEF-demo-{event['id']}",
            "file_unique_id": f"AgAD-{event['id']}",
            "file_size": 24000 + number * 137,
        }
    else:
        message["text"] = event["text"]
    return {"update_id": UPDATE_ID_BASE + number, "message": message}


def schedule_csv(events: list[dict]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["id", "changed_at", "changed_by", "note"])
    for event in events:
        writer.writerow([event["id"], event["sent_at"], event["sender"], event["text"]])
    return buffer.getvalue()


def build_files() -> dict[str, bytes]:
    deliveries = build_events()
    files: dict[str, bytes] = {}
    events = [event for event, _, _ in deliveries]
    files["events.json"] = (json.dumps(events, indent=2) + "\n").encode()

    spoken = {}
    for event, row, order in deliveries:
        if order == 0 and row["options"].get("audio"):
            spoken[event["id"]] = {"speaker": event["sender"], "text": row["options"]["say"]}
    files["voice_texts.json"] = (json.dumps(spoken, indent=2) + "\n").encode()

    # The confirmations were written after the rest; numbering them last keeps every other update id and message
    # id as it was, since live runs and channel fixtures quote them.
    numbers: dict[str, int] = {}
    telegram = [(event, row) for event, row, _ in deliveries if event["channel"] == "telegram"]
    for event, row in sorted(telegram, key=lambda pair: (
        bool(pair[1]["options"].get("historical_rework")), bool(pair[1]["options"].get("confirms"))
    )):
        numbers.setdefault(event["id"], len(numbers) + 1)
    schedule_rows = []
    for event, row, order in deliveries:
        suffix = "" if order == 0 else ".redelivery"
        if event["channel"] == "email":
            files[f"source/email/{event['id']}{suffix}.eml"] = email_bytes(event, row, order)
        elif event["channel"] == "telegram":
            update = telegram_update(event, numbers[event["id"]])
            files[f"source/telegram/{event['id']}{suffix}.json"] = (json.dumps(update, indent=2) + "\n").encode()
        else:
            schedule_rows.append(event)
    files["source/schedule/schedule-updates.csv"] = schedule_csv(schedule_rows).encode()
    return files


def main(argv: list[str]) -> int:
    files = build_files()
    if "--check" in argv:
        stale = [name for name, data in files.items() if not (HERE / name).is_file() or (HERE / name).read_bytes() != data]
        known = {str(p.relative_to(HERE)).replace("\\", "/") for p in (HERE / "source").rglob("*") if p.is_file()}
        extra = sorted(known - set(files))
        if stale or extra:
            print(f"out of date: {', '.join(stale + extra)}; run python data/messages/generate.py", file=sys.stderr)
            return 1
        print(f"up to date: {len(files)} files")
        return 0
    for name, data in files.items():
        path = HERE / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    print(f"wrote {len(files)} files to {HERE}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
