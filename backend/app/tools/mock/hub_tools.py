"""Mock hub identification tool — hardcoded plausible route combos."""

from __future__ import annotations

from typing import Any

# Pre-seeded hub knowledge for common Indian and international routes
_HUB_MAP: dict[str, list[dict[str, Any]]] = {
    "kol_ixl": [
        {"origin": "KOL", "destination": "IXL", "mode": "flight"},
        {"origin": "KOL", "destination": "DEL", "mode": "flight", "via_hub": "DEL"},
        {"origin": "DEL", "destination": "IXL", "mode": "flight"},
    ],
    "kol_leh": [
        {"origin": "KOL", "destination": "IXL", "mode": "flight"},
        {"origin": "KOL", "destination": "DEL", "mode": "flight", "via_hub": "DEL"},
        {"origin": "DEL", "destination": "IXL", "mode": "flight"},
    ],
    "bom_nrt": [
        {"origin": "BOM", "destination": "NRT", "mode": "flight"},
        {"origin": "BOM", "destination": "SIN", "mode": "flight", "via_hub": "SIN"},
        {"origin": "SIN", "destination": "NRT", "mode": "flight"},
    ],
    "del_bom": [
        {"origin": "DEL", "destination": "BOM", "mode": "flight"},
        {"origin": "DEL", "destination": "BOM", "mode": "train", "via_hub": "NDI"},
    ],
    "ccu_del": [
        {"origin": "HWH", "destination": "NDLS", "mode": "train"},
        {"origin": "KOL", "destination": "DEL", "mode": "flight"},
    ],
}


def _slug(origin: str, destination: str) -> str:
    return f"{origin.lower()[:3]}_{destination.lower()[:3]}"


class MockIdentifyHubsTool:
    name = "identify_hubs"
    description = "Mock hub identification — returns hardcoded route combos, no network calls."

    async def run(
        self,
        origin: str = "",
        destination: str = "",
        **kwargs: object,
    ) -> dict[str, Any]:
        slug = _slug(origin, destination)
        legs = _HUB_MAP.get(slug)

        if legs is None:
            # Generic fallback: direct route
            legs = [
                {"origin": origin.upper(), "destination": destination.upper(), "mode": "flight"}
            ]

        return {
            "origin": origin,
            "destination": destination,
            "route_combinations": legs,
        }
