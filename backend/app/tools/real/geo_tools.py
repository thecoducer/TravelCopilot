"""Real geo tools.

ClusterByProximityTool — fully implemented using haversine distances +
                         sklearn AgglomerativeClustering with a precomputed
                         distance matrix.
DistanceMatrixTool     — stub until Phase 5.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from sklearn.cluster import AgglomerativeClustering


def _haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in kilometres between two GPS coordinates."""
    r = 6_371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return r * 2 * math.asin(math.sqrt(a))


def _haversine_matrix(coords: np.ndarray) -> np.ndarray:
    """Return an (n × n) pairwise haversine distance matrix (km)."""
    n = len(coords)
    dist = np.zeros((n, n))
    for i in range(n):
        for j in range(i + 1, n):
            d = _haversine(coords[i, 0], coords[i, 1], coords[j, 0], coords[j, 1])
            dist[i, j] = dist[j, i] = d
    return dist


class ClusterByProximityTool:
    """Geographic clustering using true haversine distances.

    Builds a pairwise haversine distance matrix and feeds it to
    ``AgglomerativeClustering(metric='precomputed')``.  This preserves the
    correct great-circle distances rather than the Euclidean approximation
    that ``KMeans`` would use on raw lat/lng values.

    ``k`` = number of trip days, so each cluster maps to one day's activities
    in a tight geographic area.
    """

    name = "cluster_by_proximity"
    description = "Clusters experiences by geographic proximity using haversine distances."

    async def run(
        self,
        experiences: list[dict[str, Any]] | None = None,
        num_clusters: int = 3,
        **kwargs: object,
    ) -> dict[str, Any]:
        experiences = experiences or []
        if not experiences:
            return {"clusters": []}

        coords = np.array([[float(e.get("lat", 0)), float(e.get("lng", 0))] for e in experiences])
        k = max(1, min(num_clusters, len(experiences)))

        # AgglomerativeClustering requires ≥2 samples; short-circuit for trivial cases.
        if k == 1 or len(experiences) == 1:
            avg_lat = sum(e.get("lat", 0.0) for e in experiences) / len(experiences)
            avg_lng = sum(e.get("lng", 0.0) for e in experiences) / len(experiences)
            return {
                "clusters": [
                    {
                        "cluster_id": 0,
                        "centroid": {"lat": avg_lat, "lng": avg_lng},
                        "experiences": experiences,
                    }
                ]
            }

        dist_matrix = _haversine_matrix(coords)
        model = AgglomerativeClustering(n_clusters=k, metric="precomputed", linkage="average")
        labels: list[int] = model.fit_predict(dist_matrix).tolist()

        cluster_members: dict[int, list[dict[str, Any]]] = {i: [] for i in range(k)}
        for exp, label in zip(experiences, labels, strict=True):
            cluster_members[label].append(exp)

        clusters = []
        for cluster_id, members in cluster_members.items():
            if not members:
                continue
            avg_lat = sum(e.get("lat", 0.0) for e in members) / len(members)
            avg_lng = sum(e.get("lng", 0.0) for e in members) / len(members)
            clusters.append(
                {
                    "cluster_id": cluster_id,
                    "centroid": {"lat": avg_lat, "lng": avg_lng},
                    "experiences": members,
                }
            )

        return {"clusters": clusters}


class DistanceMatrixTool:
    name = "distance_matrix"
    description = "Real distance matrix via Google Distance Matrix API."

    async def run(self, **kwargs: object) -> dict[str, Any]:
        raise NotImplementedError(
            "DistanceMatrixTool requires GOOGLE_MAPS_API_KEY — implement in Phase 5."
        )
