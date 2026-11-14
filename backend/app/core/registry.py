"""Pick the real or the mock module of an area. Every area folder has a mock.py; features add real.py."""
import importlib
from types import ModuleType

from . import config


def _real(area: str) -> ModuleType | None:
    name = f"app.{area}.real"
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as error:
        if error.name != name:
            raise
        return None


def is_mock(area: str) -> bool:
    forced = config.mock_forced(area)
    if forced is True:
        return True
    real = _real(area)
    if real is None and forced is False:
        raise RuntimeError(f"USE_MOCK_{area.upper()}=false but app/{area}/real.py does not exist")
    return real is None


def area(name: str) -> ModuleType:
    if is_mock(name):
        return importlib.import_module(f"app.{name}.mock")
    return importlib.import_module(f"app.{name}.real")
