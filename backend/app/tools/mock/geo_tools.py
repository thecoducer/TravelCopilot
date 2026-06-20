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
