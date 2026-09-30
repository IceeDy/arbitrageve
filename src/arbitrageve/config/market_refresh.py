"""Canonical adaptive market refresh policy.

These values are application policy, not deployment overrides. Keeping them
outside BaseSettings prevents stale MARKET_REFRESH_* environment variables
from changing the Streamlit audit independently from the worker.
"""

MARKET_REFRESH_BASE_MINUTES = 5
MARKET_REFRESH_MIN_MINUTES = 5
MARKET_REFRESH_MAX_MINUTES = 1440
MARKET_REFRESH_REFERENCE_ORDERS = 50_000
MARKET_REFRESH_ORDER_EXPONENT = 0.5
