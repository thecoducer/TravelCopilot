"""Real hub identification tool.

In real mode the TransportSearchAgent performs hub reasoning directly via an
LLM call.  This tool returns an empty route_combinations list so the agent's
existing LLM fallback takes over — the NotImplementedError is removed so the
factory can safely instantiate this class without crashing on import or call.
"""

from __future__ import annotations

from typing import Any


class IdentifyHubsTool:
    name = "identify_hubs"
    description = "Identifies plausible hub combinations via LLM geographic reasoning."

    async def run(self, **kwargs: object) -> dict[str, Any]:
        # Return empty so TransportSearchAgent's inline LLM fallback activates.
        return {"route_combinations": []}
