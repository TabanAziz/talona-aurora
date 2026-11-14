"""Mock: a report from a registered machine is answered as not understood, and nothing is stored. Turning reports
into facts and flags is the real module's job. Spec: docs/specs/machines.md."""
from app.core import models as m
from app.core.registry import area


def report(machine_id: str, request: m.MachineReportRequest) -> m.MachineReportResult:
    if not any(machine.id == machine_id for machine in area("machine").machines()):
        raise KeyError(machine_id)
    return m.MachineReportResult(
        report_id=request.report_id, machine_id=machine_id, event_id=f"e-machine-{machine_id}-{request.report_id}",
        status="not_understood", reason="Machine reports are not read yet. Nothing was stored.",
    )


def evaluate(event: m.InboundEvent, facts: list[m.Fact]) -> list[m.Flag]:
    return []
