"""Regression tests for the degradation, calendar and enrichment fixes."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from app.agents.itinerary_compiler_agent import _fallback_day_plan
from app.agents.transport_optimizer_agent import (
    _aggregate_recommendation,
    _duration_to_minutes,
    _no_result_recommendation,
    _trim_leg,
)
from app.config import settings
from app.models.enums import BudgetVerdict, ConnectivityLevel, SectionStatus, StopKind
from app.models.itinerary import TripDays
from app.models.reports import SafetyReport
from app.models.stops import TripStop
from app.models.transport import RouteLeg, RouteWaypoint, TransportRecommendation
from app.services.itinerary_compiler_service import (
    ItineraryCompilerService,
    _connectivity_level,
    _connectivity_note,
    _derived_packing_tips,
    _with_stop_coordinates,
)


class TestDurationNormalisation:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("18543s", 309.05), (90.02, 90.02), (120, 120.0), ("0s", None), (0, None)],
    )
    def test_parses_provider_duration_formats(self, raw: object, expected: float | None) -> None:
        assert _duration_to_minutes(raw) == expected

    @pytest.mark.parametrize("raw", [None, "", "soon", True])
    def test_unusable_durations_become_none_not_zero(self, raw: object) -> None:
        """Zero would read as an instant transfer rather than missing data."""
        assert _duration_to_minutes(raw) is None

    def test_trim_leg_flags_missing_price_instead_of_zero(self) -> None:
        trimmed = _trim_leg({"duration": "18543s"})
        assert trimmed["price"] is None
        assert trimmed["price_unknown"] is True
        assert trimmed["duration_minutes"] == 309.05

    def test_trim_leg_keeps_a_real_price(self) -> None:
        trimmed = _trim_leg({"duration": 120, "price": 93})
        assert trimmed["price"] == 93.0
        assert trimmed["price_unknown"] is False


class TestTransportSchemaTolerance:
    def test_route_leg_accepts_provider_duration_string(self) -> None:
        leg = RouteLeg(mode="road", origin="A", destination="B", duration_minutes="18543s")
        assert leg.duration_minutes == 309

    def test_route_leg_accepts_a_float_duration(self) -> None:
        leg = RouteLeg(mode="road", origin="A", destination="B", duration_minutes=90.02)
        assert leg.duration_minutes == 90

    def test_route_leg_no_longer_demands_unpatchable_fields(self) -> None:
        """price_cached_at/price_disclaimer are back-filled after validation."""
        leg = RouteLeg(mode="flight", origin="KOL", destination="COK", duration_minutes=305)
        assert leg.price_cached_at is None
        assert leg.currency_code == settings.default_currency

    def test_waypoint_accepts_a_bare_label(self) -> None:
        rec = TransportRecommendation(route_waypoints=["Kochi (COK)"])
        assert rec.route_waypoints[0] == RouteWaypoint(label="Kochi (COK)", name="Kochi (COK)")


class TestAggregateRecommendation:
    def test_sums_only_priced_legs(self) -> None:
        per_leg = {
            "a": TransportRecommendation(total_cost=93.0, total_duration_minutes=305),
            "b": _no_result_recommendation("b", "INR", 1),
        }
        aggregate = _aggregate_recommendation(per_leg, "INR", 1)
        assert aggregate.total_cost == 93.0
        assert aggregate.total_duration_minutes == 305
        assert aggregate.no_result is False

    def test_reports_no_result_when_nothing_was_priced(self) -> None:
        per_leg = {"a": _no_result_recommendation("a", "INR", 1)}
        assert _aggregate_recommendation(per_leg, "INR", 1).no_result is True


class TestFoodFallback:
    def test_meals_survive_a_failed_day_plan(self) -> None:
        plan = _fallback_day_plan(2, ["Cafe A", "Cafe B", "Cafe C"])
        assert {pick.day_number for pick in plan.food} == {1, 2}
        assert len(plan.food) == 6
        assert plan.activities == []

    def test_no_venues_yields_an_empty_plan(self) -> None:
        assert _fallback_day_plan(3, []).food == []


class TestConnectivity:
    def test_high_altitude_stop_is_flagged_as_limited(self) -> None:
        stop = TripStop(
            stop_id="s1",
            name="Leh",
            sequence=1,
            altitude_meters=settings.connectivity_remote_altitude_meters + 500,
        )
        assert _connectivity_level(stop) == ConnectivityLevel.LIMITED
        assert "offline maps" in (_connectivity_note(stop) or "")

    def test_unknown_altitude_is_not_claimed_as_reliable(self) -> None:
        stop = TripStop(stop_id="s1", name="Kochi", sequence=1)
        assert _connectivity_level(stop) == ConnectivityLevel.UNKNOWN
        assert _connectivity_note(stop) is None


class TestRealityBanner:
    def test_unavailable_safety_data_never_reaches_the_banner(self) -> None:
        service = ItineraryCompilerService()
        report = SafetyReport(
            destination="Kerala",
            status=SectionStatus.UNAVAILABLE,
            seasonal_weather_summary="Data unavailable",
        )
        assert service.build_reality_banner(report, None) is None

    def test_populated_safety_data_is_shown(self) -> None:
        service = ItineraryCompilerService()
        report = SafetyReport(
            destination="Kerala",
            status=SectionStatus.POPULATED,
            seasonal_weather_summary="Warm and dry.",
        )
        assert service.build_reality_banner(report, None) == "Warm and dry"


class TestStopKindEnum:
    def test_gateway_stops_are_distinguishable(self) -> None:
        gateway = TripStop(
            stop_id="g", name="Kochi", sequence=0, stop_kind=StopKind.GATEWAY_TRANSIT
        )
        assert gateway.stop_kind == "gateway_transit"
        assert TripStop(stop_id="s", name="Munnar", sequence=1).stop_kind == StopKind.OVERNIGHT


class TestBudgetVerdictEnum:
    def test_wire_values_are_unchanged_for_existing_consumers(self) -> None:
        assert BudgetVerdict.ON_BUDGET == "on-budget"
        assert BudgetVerdict.OVER_BUDGET == "over"
        assert BudgetVerdict.UNDER_BUDGET == "under"
        assert BudgetVerdict.INCOMPLETE == "incomplete"


class TestFlexibilityClarification:
    @pytest.mark.parametrize(
        ("answer", "expected"),
        [("2", 2), ("about 3 days", 3), ("99", settings.flexibility_days_max)],
    )
    def test_parses_and_clamps_free_text(self, answer: str, expected: int) -> None:
        from app.agents.orchestrator import _parse_flexibility_answer

        assert _parse_flexibility_answer(answer) == expected

    def test_non_numeric_answer_is_rejected(self) -> None:
        from app.agents.orchestrator import _parse_flexibility_answer

        assert _parse_flexibility_answer("not sure") is None


class TestBudgetIncompleteVerdict:
    def test_unpriced_transport_is_not_reported_as_on_budget(self) -> None:
        from app.agents.budget_planner_agent import _all_legs_unpriced

        unpriced = {"a": _no_result_recommendation("a", "INR", 1)}
        assert _all_legs_unpriced(unpriced) is True
        priced = {"a": TransportRecommendation(total_cost=100.0)}
        assert _all_legs_unpriced(priced) is False

    def test_per_day_breakdown_is_not_a_flat_average(self) -> None:
        from app.agents.budget_planner_agent import _per_day_breakdown

        per_day = _per_day_breakdown(
            trip_days=3, accommodation=200.0, recurring=300.0, one_off=60.0
        )
        assert len(per_day) == 3
        # Checkout day carries no room charge, and the one-off lands on arrival.
        assert per_day[0] > per_day[1] > per_day[2]
        assert sum(per_day) == pytest.approx(560.0)


class TestSafetyDegradation:
    def test_failed_safety_report_is_marked_unavailable(self) -> None:
        report = SafetyReport(destination="Kerala", status=SectionStatus.UNAVAILABLE)
        assert report.advisory_level is None
        assert report.seasonal_weather_summary is None


class TestStopCoordinateBackfill:
    def test_stop_borrows_coordinates_from_its_chosen_stay(self) -> None:
        stop = TripStop(stop_id="munnar_01", name="Munnar", sequence=1)
        stay = SimpleNamespace(lat=10.08, lng=77.06)
        resolved = _with_stop_coordinates([stop], {"munnar_01": stay})
        assert (resolved[0].lat, resolved[0].lng) == (10.08, 77.06)

    def test_existing_coordinates_are_not_overwritten(self) -> None:
        stop = TripStop(stop_id="s1", name="Kochi", sequence=1, lat=9.9, lng=76.2)
        stay = SimpleNamespace(lat=1.0, lng=2.0)
        resolved = _with_stop_coordinates([stop], {"s1": stay})
        assert (resolved[0].lat, resolved[0].lng) == (9.9, 76.2)

    def test_missing_stay_leaves_the_stop_unlocated(self) -> None:
        stop = TripStop(stop_id="s1", name="Kochi", sequence=1)
        assert _with_stop_coordinates([stop], {})[0].lat is None


class TestPackingTipsFallback:
    def test_altitude_and_permits_produce_tips_without_the_narrator(self) -> None:
        days = [
            TripDays(
                day_number=1,
                date=date(2026, 12, 10),
                location="Leh",
                altitude_meters=settings.connectivity_remote_altitude_meters + 1000,
                permits_required=["Inner Line Permit"],
            )
        ]
        tips = _derived_packing_tips(days, SimpleNamespace(departure=date(2026, 12, 10)))
        assert any("high altitude" in tip for tip in tips)
        assert any("permits" in tip for tip in tips)
        assert any("December" in tip for tip in tips)

    def test_low_altitude_route_still_gets_a_seasonal_tip(self) -> None:
        days = [TripDays(day_number=1, date=date(2026, 12, 10), location="Kochi")]
        tips = _derived_packing_tips(days, SimpleNamespace(departure=date(2026, 12, 10)))
        assert tips == ["Check a December forecast for each stop before packing."]
