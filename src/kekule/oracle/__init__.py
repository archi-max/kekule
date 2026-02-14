"""
Kekule Oracle Generator -- turns structured Rules into executable
verification artifacts (pytest tests), runs them in Docker, and returns
pass/fail results with evidence.
"""

__version__ = "0.1.0"

from .schemas import OracleResult, OracleRunRequest, OracleType, Rule, RuleStatus

__all__ = [
    "OracleResult",
    "OracleRunRequest",
    "OracleType",
    "Rule",
    "RuleStatus",
]
