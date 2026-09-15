"""Prometheus metrics definitions for TravelCopilot.

All counters, histograms, and gauges defined here.  The ``/metrics`` endpoint
in main.py exposes them to Prometheus.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

# ── Trip planning ─────────────────────────────────────────────────────────────

trip_planning_duration_seconds = Histogram(
    "trip_planning_duration_seconds",
    "End-to-end trip planning latency",
    labelnames=["num_agents_triggered"],
    buckets=(1, 5, 10, 15, 20, 30, 45, 60, 90, 120),
)

active_planning_sessions = Gauge(
    "active_planning_sessions",
    "Number of trip planning sessions currently in progress",
)

# ── Per-agent ─────────────────────────────────────────────────────────────────

agent_duration_seconds = Histogram(
    "agent_duration_seconds",
    "Per-agent execution latency",
    labelnames=["agent_name", "layer"],
    buckets=(0.1, 0.5, 1, 2, 5, 10, 20, 30),
)

agent_error_total = Counter(
    "agent_error_total",
    "Total agent failures",
    labelnames=["agent_name", "error_type"],
)

# ── LLM ──────────────────────────────────────────────────────────────────────

llm_tokens_total = Counter(
    "llm_tokens_total",
    "Total LLM tokens consumed",
    labelnames=["agent_name", "provider", "model", "token_type"],
)

llm_cost_usd_total = Counter(
    "llm_cost_usd_total",
    "Total LLM spend in USD",
    labelnames=["agent_name"],
)

# ── Cache ─────────────────────────────────────────────────────────────────────

api_cache_hits_total = Counter(
    "api_cache_hits_total",
    "Redis cache hit/miss events",
    labelnames=["api_name", "result"],  # result: "hit" | "miss"
)

# ── Quality ───────────────────────────────────────────────────────────────────

trip_reality_score = Histogram(
    "trip_reality_score",
    "Distribution of destination crowd/season scores",
    buckets=(10, 20, 30, 40, 50, 60, 70, 80, 90, 100),
)
