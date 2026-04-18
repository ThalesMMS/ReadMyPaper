from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class _FakeExecutor:
    def __init__(self) -> None:
        self.submissions = []

    def submit(self, fn, *args, **kwargs):
        self.submissions.append((fn, args, kwargs))
        return None

    def shutdown(self, *args, **kwargs) -> None:
        return None


@pytest.fixture
def fake_executor() -> _FakeExecutor:
    return _FakeExecutor()
