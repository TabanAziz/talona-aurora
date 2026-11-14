"""Fixed outgoing messages translated through the real code path, for the replay files the tests use.

    uv run --directory backend python -m app.language.record            replay from mocks/llm
    uv run --directory backend python -m app.language.record --live     call the model and record replay files

Prints what each reader would get and whether the guard kept the translation.
"""
import os
import sys
import tempfile
from datetime import datetime, timezone

from app.core import config
from app.core import models as m


def _message(message_id: str, to: str, text: str, **extra) -> m.OutboundMessage:
    return m.OutboundMessage(id=message_id, channel="telegram", to=to, text=text, reason="language sample",
                             created_at=datetime(2026, 11, 13, 7, 0, tzinfo=timezone.utc), **extra)


# (message, target language for a stored directory language, earlier text for a reply)
SAMPLES: list[tuple[m.OutboundMessage, str | None, str | None]] = [
    (_message("o-lang-pl", "Framing crew",
              "A-201 Rev C is current. The partition between bedroom and living room in 3B shifts 300 mm north. "
              "Please confirm you have Rev C before starting the affected work.", buttons=["Confirmed"]),
     "pl", None),
    (_message("o-lang-tr", "Concrete crew", "Friday pour runs until 10:45. 4 trucks instead of 3."), "tr", None),
    (_message("o-lang-es", "Priya Shah",
              "Not yet. 2B has no rough plumbing sign-off. The superintendent decided this morning: no wall closing "
              "before the inspection sign-off is in the record.", in_reply_to="x-es1"),
     None, "¿Y la 2B? ¿Podemos cerrar esas paredes?"),
    (_message("o-lang-de", "Marco Ruiz",
              "Hold on 3B. You are on A-201 Rev B. Rev C moved the partition 300 mm north. "
              "Do not start until you confirm Rev C.", in_reply_to="x-de2"),
     None, "Wir fangen morgen um sieben mit den Trennwänden in 3B an, nach A-201 Rev B."),
    (_message("o-lang-en", "Priya Shah", "Yes. The rough plumbing inspection for 1C passed on Monday.",
              in_reply_to="x-en1"),
     None, "Roger, 1C?"),
]


def localized(sample: tuple[m.OutboundMessage, str | None, str | None]) -> m.OutboundMessage:
    from app.language import localize, localize_reply

    message, language, earlier = sample
    return localize_reply(message, earlier) if earlier is not None else localize(message, language)


def main(argv: list[str]) -> int:
    config.load_dotenv()
    os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="aurora-language-")
    if "--live" in argv:
        os.environ["USE_MOCK_LLM"] = "false"
        os.environ["LLM_RECORD"] = "true"
    for sample in SAMPLES:
        result = localized(sample)
        verdict = "translated" if result.text != sample[0].text else "english only"
        print(f"--- {sample[0].id}: {verdict}\n{result.text}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
