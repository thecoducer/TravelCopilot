"""Real geo tools.

ClusterByProximityTool — fully implemented using haversine distances +
                         sklearn AgglomerativeClustering with a precomputed
                         distance matrix.
DistanceMatrixTool     — stub until Phase 5.
"""

from __future__ import annotations

import math
from typing import Any
from urllib.parse import quote

import numpy as np
from sklearn.cluster import AgglomerativeClustering

from app.config import (
    GOOGLE_GEOCODE_FIELD_MASK,
    GOOGLE_MATRIX_FIELD_MASK,
    GOOGLE_TRAVEL_MODE_DRIVE,
    HTTP_HEADER_CONTENT_TYPE,
    HTTP_HEADER_GOOGLE_API_KEY,
    HTTP_HEADER_GOOGLE_FIELD_MASK,
    HTTP_HEADER_JSON,
    PROVIDER_GOOGLE,
    settings,
)
from app.services.external_api_client import ExternalAPIClient, get_external_api_client
from app.tools.real._helpers import invalid_request_result, provider_result, require_credential


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

    def __init__(self, client: ExternalAPIClient | None = None) -> None:
        self._client = client or get_external_api_client()

    async def run(
        self,
        origins: list[str] | None = None,
        destinations: list[str] | None = None,
        travel_mode: str = GOOGLE_TRAVEL_MODE_DRIVE,
        **kwargs: object,
    ) -> dict[str, Any]:
        origins = origins or []
        destinations = destinations or []
        empty_result: dict[str, Any] = {"rows": []}
        element_count = len(origins) * len(destinations)
        max_elements = (
            settings.google_routes_max_transit_matrix_elements
            if travel_mode == "TRANSIT"
            else settings.google_routes_max_matrix_elements
        )
        if not origins or not destinations:
            return invalid_request_result("origins and destinations are required", empty_result)
        if element_count > max_elements:
            return invalid_request_result("route matrix element limit exceeded", empty_result)
        if len(origins) + len(destinations) > settings.google_routes_max_matrix_address_count:
            return invalid_request_result("route matrix address limit exceeded", empty_result)
        require_credential(settings.google_cloud_api_key, PROVIDER_GOOGLE)
        request_body = {
            "origins": [{"waypoint": {"address": value}} for value in origins],
            "destinations": [{"waypoint": {"address": value}} for value in destinations],
            "travelMode": travel_mode,
        }
        response = await self._client.request_json(
            PROVIDER_GOOGLE,
            "POST",
            settings.google_route_matrix_url,
            headers={
                HTTP_HEADER_CONTENT_TYPE: HTTP_HEADER_JSON,
                HTTP_HEADER_GOOGLE_API_KEY: settings.google_cloud_api_key,
                HTTP_HEADER_GOOGLE_FIELD_MASK: GOOGLE_MATRIX_FIELD_MASK,
            },
            json_body=request_body,
        )
        result = self._normalize_matrix(response.payload, origins, destinations)
        return provider_result(result, response, empty_result)

    def _normalize_matrix(
        self,
        payload: dict[str, Any],
        origins: list[str],
        destinations: list[str],
    ) -> dict[str, Any]:
        rows: dict[int, list[dict[str, Any]]] = {index: [] for index in range(len(origins))}
        for element in payload.get("elements", []):
            if not isinstance(element, dict):
                continue
            origin_index = element.get("originIndex")
            destination_index = element.get("destinationIndex")
            if not isinstance(origin_index, int) or not isinstance(destination_index, int):
                continue
            if origin_index not in rows or destination_index >= len(destinations):
                continue
            status = element.get("status", {}).get("code", "OK")
            rows[origin_index].append(
                {
                    "origin": origins[origin_index],
                    "destination": destinations[destination_index],
                    "distance_km": float(element.get("distanceMeters", 0)) / 1000,
                    "duration": element.get("duration"),
                    "status": status,
                    "condition": element.get("condition"),
                }
            )
        return {
            "rows": [
                {"origin": origins[index], "elements": rows[index]} for index in range(len(origins))
            ]
        }


class GeocodeTool:
    name = "geocode"
    description = "Real Geocoding via Google Maps Geocoding API — address/place to lat/lng."

    def __init__(self, client: ExternalAPIClient | None = None) -> None:
        self._client = client or get_external_api_client()

    async def run(self, location: str = "", **kwargs: object) -> dict[str, Any]:
        empty_result: dict[str, Any] = {
            "status": "ZERO_RESULTS",
            "location": location,
            "lat": None,
            "lng": None,
        }
        if not location:
            return invalid_request_result("location is required", empty_result)
        require_credential(settings.google_cloud_api_key, PROVIDER_GOOGLE)
        endpoint = f"{settings.google_geocode_url}/{quote(location, safe='')}"
        response = await self._client.request_json(
            PROVIDER_GOOGLE,
            "GET",
            endpoint,
            headers={
                HTTP_HEADER_CONTENT_TYPE: HTTP_HEADER_JSON,
                HTTP_HEADER_GOOGLE_API_KEY: settings.google_cloud_api_key,
                HTTP_HEADER_GOOGLE_FIELD_MASK: GOOGLE_GEOCODE_FIELD_MASK,
            },
        )
        normalized_result = self._normalize_geocode(response.payload, location)
        return provider_result(normalized_result, response, empty_result)

    def _normalize_geocode(self, payload: dict[str, Any], location: str) -> dict[str, Any]:
        results = payload.get("results", [])
        first = results[0] if isinstance(results, list) and results else {}
        coordinates = first.get("location", {}) if isinstance(first, dict) else {}
        return {
            "status": "OK" if first else "ZERO_RESULTS",
            "location": location,
            "lat": coordinates.get("latitude"),
            "lng": coordinates.get("longitude"),
            "formatted_address": first.get("formattedAddress") if isinstance(first, dict) else None,
            "place_id": first.get("placeId") if isinstance(first, dict) else None,
        }
