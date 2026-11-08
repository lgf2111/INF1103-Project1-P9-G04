"""Logic Manager: applies business rules to AI-enriched records.

The class lives in ``phishreport.logic``; this module is the Logic Manager's
named entry point alongside the other three managers.
"""

from phishreport.logic import LogicManager

__all__ = ["LogicManager"]
