"""Unit tests for ItineraryCompilerService — the pure compilation engine.

These exercise the deterministic transforms directly, with no LLM and no tools,
which is the whole point of separating them out of ``ItineraryCompilerAgent``.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.models.itinerary import ActivityOption, Place, TimeSlotOptions, TripDays
from app.models.itinerary_compilation import SINGLE_STOP_ID, ActivityPick, DayPlan, TripNarrative
from app.models.reports import BudgetReport, SafetyReport, ScamEntry
from app.models.stops import DayAllocation, TripStop
from app.models.transport import StayOption
from app.models.user_profile import TripDates
from app.services.itinerary_compiler_service import (
    ItineraryCompilerService,
    MissingTripDatesError,
)


@pytest.fixture
def service() -> ItineraryCompilerService:
    return ItineraryCompilerService()


def _place(name: str) -> Place:
    return Place(
        name=name,
        description="desc",
        category="viewpoint",
        duration_minutes=60,
        price_range="Free",
        lat=34.16,
        lng=77.58,
        address=name,
    )


def _activity_option(name: str) -> ActivityOption:
    return ActivityOption(
        place=_place(name),
        rank=1,
        recommendation_reason="Great spot",
        estimated_duration_minutes=60,
    )


class TestResolveRoute:
    def test_single_destination_uses_numeric_stop_id(self, service: ItineraryCompilerService):
        state = {
            "destination": "Leh",
            "dates": TripDates(departure=date(2026, 7, 15), return_date=date(2026, 7, 17)),
        }
        route = service.resolve_route(state)

        assert route.is_multi_stop is False
        assert len(route.stops) == 1
        assert route.stops[0].stop_id == SINGLE_STOP_ID
        assert len(route.allocations) == 3
        assert all(a.stop_id == SINGLE_STOP_ID for a in route.allocations)
        assert route.allocations[0].is_checkin_day is True
        assert route.allocations[-1].is_checkout_day is True

    def test_raises_without_resolved_dates(self, service: ItineraryCompilerService):
        with pytest.raises(MissingTripDatesError):
            service.resolve_route({"destination": "Leh"})

    def test_multi_stop_reads_route_contract(self, service: ItineraryCompilerService):
        leh = TripStop(stop_id="stop-leh", name="Leh", sequence=0, nights=2)
        nubra = TripStop(stop_id="stop-nubra", name="Nubra Valley", sequence=1, nights=1)
        state = {
            "dates": TripDates(departure=date(2026, 7, 15), return_date=date(2026, 7, 17)),
            "route_discovery_status": "multi_stop_provisional",
            "stops": {"stop-leh": leh, "stop-nubra": nubra},
            "stops_by_day": {
                0: DayAllocation(day_index=0, date=date(2026, 7, 15), stop_id="stop-leh"),
                1: DayAllocation(day_index=1, date=date(2026, 7, 16), stop_id="stop-leh"),
                2: DayAllocation(day_index=2, date=date(2026, 7, 17), stop_id="stop-nubra"),
            },
        }
        route = service.resolve_route(state)

        assert route.is_multi_stop is True
        assert [s.stop_id for s in route.stops] == ["stop-leh", "stop-nubra"]
        assert route.stops_by_id["stop-nubra"].name == "Nubra Valley"
        assert len(route.allocations_for("stop-leh")) == 2
        assert len(route.allocations_for("stop-nubra")) == 1


class TestAssembleTripDays:
    def test_drops_picks_not_in_the_verified_pool(self, service: ItineraryCompilerService):
        stop = TripStop(stop_id=SINGLE_STOP_ID, name="Leh", sequence=0, nights=1)
        alloc = DayAllocation(day_index=0, date=date(2026, 7, 15), stop_id=SINGLE_STOP_ID)
        plan = DayPlan(
            activities=[
                ActivityPick(
                    day_number=1,
                    slot="morning",
                    experience_name="Invented Place",
                    recommendation_reason="Sounds nice",
                )
            ]
        )

        days = service.assemble_trip_days(
            stop, [alloc], plan, experience_pool={}, food_pool={}, stop_id=None, route_version=None
        )

        assert days[0].morning.options == []


class TestResolveConflicts:
    def test_trims_over_packed_slot_to_configured_maximum(self, service: ItineraryCompilerService):
        day = TripDays(
            day_number=1,
            date=date(2026, 7, 15),
            location="Leh",
            morning=TimeSlotOptions(
                slot="morning",
                options=[_activity_option("A"), _activity_option("B"), _activity_option("C")],
            ),
        )
        resolved = service.resolve_conflicts(
            [day],
            conflict_names=set(),
            duration_flags=[{"day": day.date.isoformat(), "slot": "morning"}],
        )
        assert len(resolved[0].morning.options) == 2  # settings.itinerary_max_activities_per_slot

    def test_drops_closed_venue_by_name(self, service: ItineraryCompilerService):
        day = TripDays(
            day_number=1,
            date=date(2026, 7, 15),
            location="Leh",
            morning=TimeSlotOptions(slot="morning", options=[_activity_option("Closed Museum")]),
        )
        resolved = service.resolve_conflicts(
            [day], conflict_names={"Closed Museum"}, duration_flags=[]
        )
        assert resolved[0].morning.options == []
        assert resolved[0].morning.unresolved_note is not None


class TestInjectStays:
    def test_repeats_full_stay_across_a_multi_night_stop(self, service: ItineraryCompilerService):
        stay = StayOption(
            name="Grand Dragon",
            address="Leh",
            city="Leh",
            price_per_night=8000.0,
            currency_code="INR",
            rating=4.5,
            review_count=200,
        )
        days = [
            TripDays(day_number=i, date=date(2026, 7, 14 + i), location="Leh", stop_id="stop-leh")
            for i in range(1, 4)
        ]
        state = {"stays_shortlist_by_stop": {"stop-leh": [stay]}}

        injected = service.inject_stays(days, state)

        assert all(day.stay_options.nights_at_location == 3 for day in injected)
        assert all(day.stay_options.options == [stay] for day in injected)


class TestInjectBudget:
    def test_maps_per_day_breakdown_by_day_number(self, service: ItineraryCompilerService):
        days = [
            TripDays(day_number=i, date=date(2026, 7, 14 + i), location="Leh") for i in range(1, 4)
        ]
        report = BudgetReport(
            currency_code="INR",
            total_estimated_cost=30000.0,
            per_day_breakdown=[9000.0, 10000.0, 11000.0],
            vs_budget_verdict="on-budget",
        )
        injected = service.inject_budget(days, report)
        assert [day.estimated_cost for day in injected] == [9000.0, 10000.0, 11000.0]
        assert all(day.currency_code == "INR" for day in injected)


class TestPromeTemplates:
    def test_render_safety_briefing_is_deterministic(self, service: ItineraryCompilerService):
        report = SafetyReport(
            destination="Leh",
            advisory_level="Exercise normal caution",
            crowd_level="Moderate",
            top_scams=[ScamEntry(name="Taxi scam", description="d", how_to_avoid="Use meters")],
        )
        text = service.render_safety_briefing(report)
        assert text == service.render_safety_briefing(report)
        assert "Taxi scam" in text
        assert "Exercise normal caution" in text

    def test_build_reality_banner_combines_safety_and_budget(
        self, service: ItineraryCompilerService
    ):
        safety = SafetyReport(destination="Leh", advisory_level="Normal", season_label="Summer")
        budget = BudgetReport(
            currency_code="INR", total_estimated_cost=1000.0, vs_budget_verdict="under"
        )
        banner = service.build_reality_banner(safety, budget)
        assert "Summer season" in banner
        assert "under" in banner


class TestAssertUpstreamAbsorbed:
    def test_flags_stays_that_never_reached_any_day(self, service: ItineraryCompilerService):
        stay = StayOption(
            name="Grand Dragon",
            address="Leh",
            city="Leh",
            price_per_night=8000.0,
            currency_code="INR",
            rating=4.5,
            review_count=200,
        )
        state = {"dates": TripDates(departure=date(2026, 7, 15), return_date=date(2026, 7, 15))}
        route = service.resolve_route(state)
        days = service.build_stub_days("Leh", route.allocations)
        itinerary = service.build_itinerary(state, route, days, None, TripNarrative())

        dropped = service.assert_upstream_absorbed(itinerary, {**state, "stays_shortlist": [stay]})
        assert "stays_shortlist" in dropped
