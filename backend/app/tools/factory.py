"""ToolFactory — single source of truth for tool instantiation.

Usage:
    factory = ToolFactory()          # respects settings.mock_external_apis
    factory = ToolFactory(mock=True) # force recorded-response replay (tests)
    tool = factory.get("search_flights")
"""

from __future__ import annotations

from datetime import UTC, datetime
from importlib import import_module
from typing import Any, NamedTuple

from app.config import (
    PROVIDER_APPLICATION,
    PROVIDER_GOOGLE,
    PROVIDER_OPEN_EXCHANGE_RATES,
    PROVIDER_SERPAPI,
    PROVIDER_TAVILY,
    TOOL_EMPTY_RESULT_SHAPES,
    TOOL_RESPONSE_ARGUMENTS_KEY,
    TOOL_RESPONSE_ERROR_FIELD_KEY,
    TOOL_RESPONSE_ERROR_KEY,
    TOOL_RESPONSE_EXCHANGES_KEY,
    TOOL_RESPONSE_EXECUTION_MODE_KEY,
    TOOL_RESPONSE_META_ERROR_KEY,
    TOOL_RESPONSE_META_FETCHED_AT_KEY,
    TOOL_RESPONSE_META_KEY,
    TOOL_RESPONSE_META_PROVIDER_KEY,
    TOOL_RESPONSE_META_REPLAY_KEY,
    TOOL_RESPONSE_META_REQUEST_FINGERPRINT_KEY,
    TOOL_RESPONSE_META_RETRY_COUNT_KEY,
    TOOL_RESPONSE_META_STATUS_KEY,
    TOOL_RESPONSE_NORMALIZED_RESULT_KEY,
    TOOL_RESPONSE_PROVIDER_KEY,
    TOOL_RESPONSE_REAL_MODE,
    TOOL_RESPONSE_RECORDED_AT_KEY,
    TOOL_RESPONSE_REPLAY_HIT,
    TOOL_RESPONSE_REPLAY_MISS,
    TOOL_RESPONSE_SCHEMA_VERSION,
    TOOL_RESPONSE_SCHEMA_VERSION_KEY,
    TOOL_RESPONSE_STATUS_ERROR,
    TOOL_RESPONSE_STATUS_KEY,
    TOOL_RESPONSE_STATUS_SUCCESS,
    TOOL_RESPONSE_TOOL_NAME_KEY,
    TOOL_RUNTIME_DURATION_MS_KEY,
    TOOL_RUNTIME_ERROR_KEY,
    TOOL_RUNTIME_EXCHANGES_KEY,
    TOOL_RUNTIME_KEY,
    TOOL_RUNTIME_RETRY_COUNT_KEY,
    TOOL_RUNTIME_STATUS_KEY,
    settings,
)
from app.services.tool_response_store import ToolResponseStore
from app.tools.base import BaseTool


class _ToolEntry(NamedTuple):
    """Maps a logical tool name to its module file and real class name.

    Mock mode replays recordings through the shared invocation wrapper; it does
    not load a separate tool implementation.
    """

    module: str  # module file under tools/real/ e.g. "serpapi_tools"
    cls: str  # real class name                   e.g. "FlightSearchTool"


# Registry: logical tool name -> real adapter entry.
_REGISTRY: dict[str, _ToolEntry] = {
    "search_flights": _ToolEntry("serpapi_tools", "FlightSearchTool"),
    "search_hotels": _ToolEntry("serpapi_tools", "HotelSearchTool"),
    "search_transit": _ToolEntry("transit_tools", "TransitSearchTool"),
    "search_road_routes": _ToolEntry("road_route_tools", "RoadRouteTool"),
    "search_taxi_info": _ToolEntry("taxi_tools", "TaxiInfoTool"),
    "search_places": _ToolEntry("places_tools", "PlaceSearchTool"),
    "place_details": _ToolEntry("places_tools", "PlaceDetailsTool"),
    "tavily_search": _ToolEntry("tavily_tools", "TavilySearchTool"),
    "visa_centre_search": _ToolEntry("visa_tools", "VisaCentreSearchTool"),
    "embassy_search": _ToolEntry("visa_tools", "EmbassySearchTool"),
    "rental_search": _ToolEntry("rental_tools", "RentalSearchTool"),
    "fuel_price": _ToolEntry("rental_tools", "FuelPriceTool"),
    "cluster_by_proximity": _ToolEntry("geo_tools", "ClusterByProximityTool"),
    "distance_matrix": _ToolEntry("geo_tools", "DistanceMatrixTool"),
    "geocode": _ToolEntry("geo_tools", "GeocodeTool"),
    "currency_convert": _ToolEntry("fx_tools", "CurrencyConvertTool"),
    "enforce_opening_hours": _ToolEntry("opening_hours_tools", "EnforceOpeningHoursTool"),
    "validate_day_duration": _ToolEntry("opening_hours_tools", "ValidateDayDurationTool"),
}

_PROVIDER_BY_TOOL: dict[str, str] = {
    "search_flights": PROVIDER_SERPAPI,
    "search_hotels": PROVIDER_SERPAPI,
    "tavily_search": PROVIDER_TAVILY,
    "visa_centre_search": PROVIDER_TAVILY,
    "rental_search": PROVIDER_GOOGLE,
    "fuel_price": PROVIDER_TAVILY,
    "search_places": PROVIDER_GOOGLE,
    "place_details": PROVIDER_GOOGLE,
    "search_transit": PROVIDER_GOOGLE,
    "search_road_routes": PROVIDER_GOOGLE,
    "search_taxi_info": PROVIDER_GOOGLE,
    "embassy_search": PROVIDER_GOOGLE,
    "distance_matrix": PROVIDER_GOOGLE,
    "geocode": PROVIDER_GOOGLE,
    "currency_convert": PROVIDER_OPEN_EXCHANGE_RATES,
}


class _InvocationTool:
    """Apply the two-mode replay/capture contract to one real tool."""

    def __init__(
        self,
        tool: BaseTool | None,
        tool_name: str,
        provider: str,
        mock_mode: bool,
        response_store: ToolResponseStore,
    ) -> None:
        self._tool = tool
        self._tool_name = tool_name
        self._provider = provider
        self._mock_mode = mock_mode
        self._response_store = response_store
        self.name = tool_name
        self.description = tool.description if tool else f"Recorded response tool: {tool_name}"

    async def run(self, **kwargs: object) -> dict[str, Any]:
        arguments = dict(kwargs)
        request_fingerprint = self._response_store.fingerprint(arguments)
        if self._mock_mode:
            return self._run_mock(request_fingerprint)
        return await self._run_real(arguments, request_fingerprint, kwargs)

    def _run_mock(self, request_fingerprint: str) -> dict[str, Any]:
        envelope = self._response_store.find_latest_success(self._tool_name, request_fingerprint)
        if envelope is None:
            return self._missing_recording(request_fingerprint)
        result = envelope.get(TOOL_RESPONSE_NORMALIZED_RESULT_KEY)
        if not isinstance(result, dict):
            return self._missing_recording(request_fingerprint)
        return self._with_metadata(
            result,
            TOOL_RESPONSE_STATUS_SUCCESS,
            request_fingerprint,
            TOOL_RESPONSE_REPLAY_HIT,
            datetime.now(UTC),
            None,
        )

    async def _run_real(
        self,
        arguments: dict[str, Any],
        request_fingerprint: str,
        keyword_arguments: dict[str, object],
    ) -> dict[str, Any]:
        started_at = datetime.now(UTC)
        try:
            if self._tool is None:
                raise RuntimeError(f"Real tool is unavailable: {self._tool_name}")
            result = await self._tool.run(**keyword_arguments)
            runtime = self._extract_runtime(result)
            status = str(runtime.get(TOOL_RUNTIME_STATUS_KEY, TOOL_RESPONSE_STATUS_SUCCESS))
            error = self._runtime_error(runtime)
        except Exception as exc:
            result = self._error_result(exc, request_fingerprint)
            runtime = {}
            status = TOOL_RESPONSE_STATUS_ERROR
            error = {"type": type(exc).__name__, "message": str(exc)}
        response = self._with_metadata(
            result,
            status,
            request_fingerprint,
            TOOL_RESPONSE_REPLAY_MISS,
            started_at,
            error,
            int(runtime.get(TOOL_RUNTIME_DURATION_MS_KEY, 0)),
            int(runtime.get(TOOL_RUNTIME_RETRY_COUNT_KEY, 0)),
        )
        self._record(
            arguments,
            request_fingerprint,
            response,
            status,
            started_at,
            error,
            list(runtime.get(TOOL_RUNTIME_EXCHANGES_KEY, [])),
        )
        return response

    def _missing_recording(self, request_fingerprint: str) -> dict[str, Any]:
        error = {
            "type": "missing_recording",
            "message": f"No recorded response for {self._tool_name} and request fingerprint",
        }
        return {
            **TOOL_EMPTY_RESULT_SHAPES.get(self._tool_name, {}),
            TOOL_RESPONSE_ERROR_KEY: error,
            TOOL_RESPONSE_META_KEY: {
                TOOL_RESPONSE_META_STATUS_KEY: TOOL_RESPONSE_STATUS_ERROR,
                TOOL_RESPONSE_META_PROVIDER_KEY: self._provider,
                TOOL_RESPONSE_META_REPLAY_KEY: "replay_miss",
                TOOL_RESPONSE_META_REQUEST_FINGERPRINT_KEY: request_fingerprint,
                TOOL_RESPONSE_META_ERROR_KEY: error,
            },
        }

    def _error_result(self, exception: Exception, request_fingerprint: str) -> dict[str, Any]:
        return {
            **TOOL_EMPTY_RESULT_SHAPES.get(self._tool_name, {}),
            TOOL_RESPONSE_ERROR_KEY: {
                "type": type(exception).__name__,
                "message": str(exception),
            },
            TOOL_RESPONSE_META_KEY: {
                TOOL_RESPONSE_META_STATUS_KEY: TOOL_RESPONSE_STATUS_ERROR,
                TOOL_RESPONSE_META_REQUEST_FINGERPRINT_KEY: request_fingerprint,
            },
        }

    def _with_metadata(
        self,
        result: dict[str, Any],
        status: str,
        request_fingerprint: str,
        replay: str,
        started_at: datetime,
        error: dict[str, str] | None,
        duration_ms: int = 0,
        retry_count: int = 0,
    ) -> dict[str, Any]:
        metadata = {
            TOOL_RESPONSE_META_STATUS_KEY: status,
            TOOL_RESPONSE_META_PROVIDER_KEY: self._provider,
            TOOL_RESPONSE_META_REPLAY_KEY: replay,
            TOOL_RESPONSE_META_REQUEST_FINGERPRINT_KEY: request_fingerprint,
            TOOL_RESPONSE_META_FETCHED_AT_KEY: started_at.isoformat().replace("+00:00", "Z"),
            TOOL_RESPONSE_META_RETRY_COUNT_KEY: retry_count,
            "duration_ms": duration_ms,
        }
        if error is not None:
            metadata[TOOL_RESPONSE_META_ERROR_KEY] = error
        return {**result, TOOL_RESPONSE_META_KEY: metadata}

    def _record(
        self,
        arguments: dict[str, Any],
        request_fingerprint: str,
        result: dict[str, Any],
        status: str,
        started_at: datetime,
        error: dict[str, str] | None,
        exchanges: list[dict[str, Any]],
    ) -> None:
        self._response_store.write(
            {
                TOOL_RESPONSE_SCHEMA_VERSION_KEY: TOOL_RESPONSE_SCHEMA_VERSION,
                TOOL_RESPONSE_TOOL_NAME_KEY: self._tool_name,
                TOOL_RESPONSE_PROVIDER_KEY: self._provider,
                TOOL_RESPONSE_EXECUTION_MODE_KEY: TOOL_RESPONSE_REAL_MODE,
                TOOL_RESPONSE_RECORDED_AT_KEY: started_at.isoformat().replace("+00:00", "Z"),
                "request_fingerprint": request_fingerprint,
                TOOL_RESPONSE_ARGUMENTS_KEY: arguments,
                TOOL_RESPONSE_EXCHANGES_KEY: exchanges,
                TOOL_RESPONSE_NORMALIZED_RESULT_KEY: result,
                TOOL_RESPONSE_STATUS_KEY: status,
                TOOL_RESPONSE_ERROR_FIELD_KEY: error,
            }
        )

    def _extract_runtime(self, result: dict[str, Any]) -> dict[str, Any]:
        runtime = result.pop(TOOL_RUNTIME_KEY, {})
        return runtime if isinstance(runtime, dict) else {}

    def _runtime_error(self, runtime: dict[str, Any]) -> dict[str, str] | None:
        error = runtime.get(TOOL_RUNTIME_ERROR_KEY)
        return error if isinstance(error, dict) else None


class ToolFactory:
    def __init__(self, mock: bool | None = None) -> None:
        self._mock: bool = mock if mock is not None else settings.mock_external_apis
        self._response_store = ToolResponseStore()

    @property
    def is_mock(self) -> bool:
        return self._mock

    def get(self, tool_name: str) -> BaseTool:
        if tool_name not in _REGISTRY:
            raise KeyError(f"Unknown tool '{tool_name}'. Valid names: {sorted(_REGISTRY)}")
        entry = _REGISTRY[tool_name]
        provider = _PROVIDER_BY_TOOL.get(tool_name, PROVIDER_APPLICATION)
        if self._mock:
            return _InvocationTool(
                None,
                tool_name,
                provider,
                True,
                self._response_store,
            )
        module = import_module(f"app.tools.real.{entry.module}")
        cls = getattr(module, entry.cls)
        tool: BaseTool = cls()
        return _InvocationTool(
            tool,
            tool_name,
            provider,
            False,
            self._response_store,
        )

    def all_names(self) -> list[str]:
        return list(_REGISTRY)
