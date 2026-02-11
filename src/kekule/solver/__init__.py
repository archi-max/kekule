"""
Kekule Solver Agent

An autonomous agent that solves programming questions using Claude Agent SDK.
"""

__version__ = "0.1.0"

from .agent import ExpertSolverAgent, solve_question
from .schemas import Question, SolverResponse, PreviousAttempt

__all__ = [
    "ExpertSolverAgent",
    "solve_question",
    "Question",
    "SolverResponse",
    "PreviousAttempt",
]
