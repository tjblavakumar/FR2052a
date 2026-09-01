"""FR 2052a liquidity surveillance analytics engine (phase 2).

Consumes phase-1 mock submission files (produced by ``fr2052a_mockgen``) and
performs supervisory-style liquidity analysis: regulatory-grounded metrics, a
declarative rule engine, trend analysis, statistical anomaly detection,
cross-institution comparison, and a simple (experimental) trend forecast.

All analysis runs on synthetic data. Metrics are documented approximations of
the FR 2052a / Regulation WW liquidity measures, not exact regulatory
calculations; see ANALYTICS_NOTES.md.
"""
from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
