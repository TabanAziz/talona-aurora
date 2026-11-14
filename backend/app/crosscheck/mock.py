"""Mock: no cross-sheet findings, so a test that forces every area to its mock stays independent of this one."""
from app.core import models as m


def check(diff: m.DrawingDiff) -> list:
    return []


def on_diff(diff: m.DrawingDiff, event: m.InboundEvent) -> None:
    return None
