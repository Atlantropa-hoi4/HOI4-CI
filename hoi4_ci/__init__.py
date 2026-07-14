"""Dependency-free static checks for Hearts of Iron IV mods."""

from .checker import Checker
from .models import CheckResult, Diagnostic

__all__ = ["CheckResult", "Checker", "Diagnostic"]
__version__ = "0.1.0"
