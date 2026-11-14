"""Mock: no learned names."""
from app.core import models as m


def known() -> list[dict]:
    return []


def learn() -> list[m.RecordEntry]:
    return []
