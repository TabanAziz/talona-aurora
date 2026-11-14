"""Mock: recognises the prepared instructions of the scenario by a phrase."""
from app.core import models as m
from app.core import scenario


def interpret(text: str) -> m.CommandResponse:
    for phrase, raw in scenario.load()["commands"].items():
        if phrase in text.lower():
            return m.CommandResponse.model_validate(raw)
    return m.CommandResponse(message="I can not turn that into an action yet.")
