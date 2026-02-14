"""Shared fixtures for the kekule test suite."""

import pytest


# Realistic pytest output used across tests
_PYTEST_OUTPUT_SHORT = """\
============================= test session starts =============================
collected 2 items

tests/test_core.py::test_basic PASSED
tests/test_core.py::test_edge PASSED

============================== 2 passed in 0.3s ==============================
"""

_PYTEST_OUTPUT_LONG = "\n".join(
    [
        "============================= test session starts =============================",
        "platform linux -- Python 3.11.0, pytest-7.2.0, pluggy-1.0.0",
        "rootdir: /home/user/project",
        "collected 25 items",
        "",
        "tests/test_core.py::test_basic PASSED",
        "tests/test_core.py::test_validate PASSED",
        "tests/test_core.py::test_edge FAILED",
        "tests/test_utils.py::test_helper PASSED",
        "",
        "FAILURES",
        "_____________________________ test_edge _____________________________",
        "",
        "self = <tests.test_core.TestCore object at 0x7f1234>",
        "",
        "    def test_edge(self):",
        '        x = compute(None)',
        ">       assert x == 0",
        "E       TypeError: unsupported operand type(s) for +: 'NoneType' and 'int'",
        "",
        'File "/home/user/project/tests/test_core.py", line 42, in test_edge',
        "    assert x == 0",
        'File "/home/user/project/src/core.py", line 15, in compute',
        "    return x + 1",
        "TypeError: unsupported operand type(s) for +: 'NoneType' and 'int'",
        "",
        "========================= short test summary info =========================",
        "FAILED tests/test_core.py::test_edge - TypeError: unsupported operand type(s)",
        "========================= 1 failed, 3 passed in 0.5s =========================",
    ]
)


@pytest.fixture
def PYTEST_OUTPUT_SHORT() -> str:
    return _PYTEST_OUTPUT_SHORT


@pytest.fixture
def PYTEST_OUTPUT_LONG() -> str:
    return _PYTEST_OUTPUT_LONG
