"""Mock geo tools — clustering and distance matrix."""

from __future__ import annotations

from typing import Any


def _simple_cluster(experiences: list[dict[str, Any]], num_clusters: int) -> list[dict[str, Any]]:
    """Divide experiences sequentially into n roughly-equal clusters."""
    if not experiences:
        return []
    k = max(1, min(num_clusters, len(experiences)))
    chunk_size = max(1, len(experiences) // k)
    clusters = []
    for i in range(k):
        start = i * chunk_size
        end = start + chunk_size if i < k - 1 else len(experiences)
        members = experiences[start:end]
        if not members:
            continue
        avg_lat = sum(e.get("lat", 0.0) for e in members) / len(members)
        avg_lng = sum(e.get("lng", 0.0) for e in members) / len(members)
        clusters.append(
            {
                "cluster_id": i,
                "centroid": {"lat": avg_lat, "lng": avg_lng},
                "experiences": members,
            }
        )
    return clusters


class MockClusterByProximityTool:
    name = "cluster_by_proximity"
    description = "Mock geo-clustering — simple sequential split, no network calls."

    async def run(
        self,
        experiences: list[dict[str, Any]] | None = None,
        num_clusters: int = 3,
        **kwargs: object,
    ) -> dict[str, Any]:
        return {"clusters": _simple_cluster(experiences or [], num_clusters)}


class MockDistanceMatrixTool:
    name = "distance_matrix"
    description = "Mock distance matrix — returns plausible fixed distances, no network calls."

    async def run(
        self,
        origins: list[str] | None = None,
        destinations: list[str] | None = None,
        **kwargs: object,
    ) -> dict[str, Any]:
        origins = origins or []
        destinations = destinations or []
        rows = []
        for orig in origins:
            elements = []
            for dest in destinations:
                elements.append(
                    {
                        "origin": orig,
                        "destination": dest,
                        "distance_km": 25.0,
                        "duration_minutes": 45,
                        "status": "OK",
                    }
                )
            rows.append({"origin": orig, "elements": elements})
        return {"rows": rows}


_KNOWN_COORDINATES: dict[str, tuple[float, float]] = {
    "leh": (34.1526, 77.5771),
    "lisbon": (38.7223, -9.1393),
    "kolkata": (22.5726, 88.3639),
    "delhi": (28.6139, 77.2090),
    "new delhi": (28.6139, 77.2090),
    "mumbai": (19.0760, 72.8777),
    "tokyo": (35.6762, 139.6503),
    "osaka": (34.6937, 135.5023),
    "nubra": (34.6863, 77.5673),
    "pangong": (33.7595, 78.6674),
    "hanle": (32.7753, 78.9664),
    "goa": (15.2993, 74.1240),
    "dirang": (27.3570, 92.2384),
    "tawang": (27.5862, 91.8594),
    "bomdila": (27.2645, 92.4159),
    "guwahati": (26.1445, 91.7362),
    "sintra": (38.8029, -9.3817),
    "cascais": (38.6979, -9.4215),
    "porto": (41.1579, -8.6291),
}


class MockGeocodeTool:
    name = "geocode"
    description = "Mock geocoding tool — returns deterministic lat/lng coordinates, no network calls."

    async def run(self, location: str = "", **kwargs: object) -> dict[str, Any]:
        loc = location.lower().split(",")[0].strip()
        if loc in _KNOWN_COORDINATES:
            lat, lng = _KNOWN_COORDINATES[loc]
        else:
            h = abs(hash(loc))
            lat = 20.0 + (h % 5000) / 100.0
            lng = 70.0 + ((h // 5000) % 5000) / 100.0
        return {
            "status": "OK",
            "location": location,
            "lat": lat,
            "lng": lng,
            "formatted_address": location.title(),
        }
