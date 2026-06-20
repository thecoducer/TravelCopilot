"""Unit tests for all Pydantic models (P1-2)."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from app.models.itinerary import (
    ActivityOption,
    ClarificationRequest,
    Day,
    Experience,
    FoodOptions,
    FoodVenue,
    Itinerary,
    Place,
    StayOptions,
    TimeSlotOptions,
    TripSegment,
)
from app.models.reports import (
    AgentTokenUsage,
    BudgetReport,
    DestinationContextReport,
    FxRateEntry,
    ScamEntry,
    ScamSafetyReport,
    SelfDriveReport,
    VisaReport,
    VisaSource,
)
from app.models.transport import RouteLeg, StayOption
from app.models.user_profile import (
    BudgetPreference,
    BudgetTier,
    ClarificationPrompt,
    HotelStyle,
    TripDates,
    UserProfile,
)

# ── UserProfile models ───────────────────────────────────────────────────────


class TestTripDates:
    def test_basic(self):
        d = TripDates(departure=date(2026, 10, 1), return_date=date(2026, 10, 4))
        assert d.trip_days == 3

    def test_no_return_date(self):
        d = TripDates(departure=date(2026, 10, 1))
        assert d.trip_days == 1

    def test_same_day_trip(self):
        d = TripDates(departure=date(2026, 10, 1), return_date=date(2026, 10, 1))
        assert d.trip_days == 1  # clamped to 1

    def test_flexibility_defaults(self):
        d = TripDates(departure=date(2026, 9, 1))
        assert d.flexibility_days == 0
        assert d.night_travel_ok is True

    def test_flexibility_configured(self):
        d = TripDates(
            departure=date(2026, 9, 1),
            return_date=date(2026, 9, 6),
            flexibility_days=2,
            night_travel_ok=False,
        )
        assert d.flexibility_days == 2
        assert d.night_travel_ok is False


class TestBudgetPreference:
    def test_default_mid(self):
        bp = BudgetPreference()
        assert bp.tier == BudgetTier.mid

    def test_budget_tier(self):
        bp = BudgetPreference(tier=BudgetTier.budget, total_budget_inr=50000)
        assert bp.tier == BudgetTier.budget
        assert bp.total_budget_inr == 50000

    def test_negative_budget_rejected(self):
        with pytest.raises(ValueError):
            BudgetPreference(total_budget_inr=-1)


class TestClarificationPrompt:
    def test_fields_required(self):
        cp = ClarificationPrompt(
            field="dates",
            question="What dates are you travelling?",
            reason="Needed to check availability and prices.",
        )
        assert cp.field == "dates"
        assert "dates" in cp.question.lower()


class TestUserProfile:
    def test_defaults(self):
        up = UserProfile(user_id="u1")
        assert up.preferred_currency == "INR"
        assert up.budget_tier == BudgetTier.mid
        assert up.interests == []
        assert up.fitness_level is None
        assert up.travel_style is None

    def test_full_profile(self):
        up = UserProfile(
            user_id="u2",
            home_city="Mumbai",
            passport_country="India",
            interests=["food", "history"],
            hotel_style=HotelStyle.boutique,
            budget_tier=BudgetTier.luxury,
            travel_style="cultural",
            fitness_level="moderate",
        )
        assert up.hotel_style == HotelStyle.boutique
        assert up.travel_style == "cultural"
        assert up.fitness_level == "moderate"

    def test_altitude_experience(self):
        up = UserProfile(user_id="u3", altitude_experience=True)
        assert up.altitude_experience is True

    def test_no_altitude_experience_by_default(self):
        up = UserProfile(user_id="u4")
        assert up.altitude_experience is None


# ── Transport models ─────────────────────────────────────────────────────────


class TestRouteLeg:
    def test_required_fields(self):
        leg = RouteLeg(
            mode="flight",
            operator="IndiGo",
            origin="KOL",
            destination="DEL",
            duration_minutes=120,
            cost=5000,
            currency_code="INR",
            price_cached_at=datetime.now(tz=UTC),
            price_disclaimer="Price captured 2h ago — verify before booking.",
        )
        assert leg.price_disclaimer != ""
        assert isinstance(leg.price_cached_at, datetime)
        assert leg.stops == 0
        assert leg.flight_number is None

    def test_flight_with_layover(self):
        leg = RouteLeg(
            mode="flight",
            operator="Air India",
            origin="KOL",
            destination="IXL",
            duration_minutes=195,
            cost=8200,
            currency_code="INR",
            price_cached_at=datetime.now(tz=UTC),
            price_disclaimer="Indicative price.",
            flight_number="AI-445",
            stops=1,
            layover_at="DEL",
            baggage_allowance="15 kg checked + 7 kg cabin",
            cancellation_policy="Non-refundable",
        )
        assert leg.flight_number == "AI-445"
        assert leg.stops == 1
        assert leg.layover_at == "DEL"
        assert leg.baggage_allowance == "15 kg checked + 7 kg cabin"
        assert leg.cancellation_policy == "Non-refundable"

    def test_negative_cost_rejected(self):
        with pytest.raises(ValueError):
            RouteLeg(
                mode="flight",
                operator="x",
                origin="A",
                destination="B",
                duration_minutes=60,
                cost=-1,
                currency_code="INR",
                price_cached_at=datetime.now(tz=UTC),
                price_disclaimer="x",
            )


class TestStayOption:
    def test_defaults(self):
        stay = StayOption(
            name="Hotel A",
            address="1 Main St",
            city="Tokyo",
            price_per_night=8000,
            currency_code="JPY",
            rating=4.2,
            review_count=300,
        )
        assert stay.amenities == []
        assert stay.price_disclaimer is None
        assert stay.check_in is None
        assert stay.check_out is None

    def test_booking_fields(self):
        stay = StayOption(
            name="The Grand Dragon",
            address="Old Leh Road",
            city="Leh",
            price_per_night=4500,
            currency_code="INR",
            rating=4.4,
            review_count=210,
            check_in="2:00 PM",
            check_out="11:00 AM",
            free_cancellation_until="2026-09-01",
            price_per_night_inr=4500.0,
        )
        assert stay.check_in == "2:00 PM"
        assert stay.free_cancellation_until == "2026-09-01"
        assert stay.price_per_night_inr == 4500.0


# ── Itinerary models ─────────────────────────────────────────────────────────


class TestPlace:
    def test_basic(self):
        p = Place(
            name="Osaka Castle",
            description="Historic castle",
            category="tourist_attraction",
            duration_minutes=150,
            price_range="¥600",
            lat=34.6873,
            lng=135.5262,
            address="1-1 Osakajo, Chuo-ku",
        )
        assert p.name == "Osaka Castle"
        assert p.duration_minutes == 150
        assert p.rating is None  # optional
        assert p.review_count is None

    def test_rating_carried_from_api(self):
        p = Place(
            name="Magnetic Hill",
            description="Optical illusion road near Leh",
            category="Natural Feature",
            duration_minutes=30,
            price_range="Free",
            lat=34.2208,
            lng=77.4128,
            address="Leh-Kargil-Srinagar Highway",
            rating=4.1,
            review_count=2840,
        )
        assert p.rating == 4.1
        assert p.review_count == 2840

    def test_rating_bounds(self):
        with pytest.raises(ValueError):
            Place(
                name="X",
                description="X",
                category="X",
                duration_minutes=10,
                price_range="Free",
                lat=0,
                lng=0,
                address="X",
                rating=5.5,  # > 5
            )

    def test_duration_non_negative(self):
        with pytest.raises(ValueError):
            Place(
                name="X",
                description="X",
                category="X",
                duration_minutes=-1,
                price_range="Free",
                lat=0,
                lng=0,
                address="X",
            )


class TestFoodVenue:
    def test_meal_types(self):
        fv = FoodVenue(
            name="Ichiran",
            category="restaurant",
            cuisine="Ramen",
            price_range="¥900-1200",
            rating=4.2,
            address="Dotonbori",
            meal_types=["lunch", "dinner"],
        )
        assert "lunch" in fv.meal_types

    def test_rating_bounds(self):
        with pytest.raises(ValueError):
            FoodVenue(
                name="X",
                category="restaurant",
                cuisine="X",
                price_range="X",
                rating=6.0,
                address="X",
            )

    def test_booking_and_review_fields(self):
        fv = FoodVenue(
            name="Bon Appetit",
            category="restaurant",
            cuisine="Continental",
            price_range="₹400-700",
            rating=4.3,
            address="Fort Road, Leh",
            review_count=182,
            booking_url="https://zomato.com/leh/bon-appetit",
        )
        assert fv.review_count == 182
        assert fv.booking_url is not None


class TestExperience:
    def test_source_field(self):
        exp = Experience(
            name="Senso-ji",
            type="tourist_attraction",
            description="Ancient temple",
            duration_hours=2.0,
            price_range="Free",
            lat=35.7148,
            lng=139.7967,
            source="google_places",
        )
        assert exp.source == "google_places"
        assert exp.address is None
        assert exp.rating is None

    def test_api_fields_carried_through(self):
        exp = Experience(
            name="Pangong Lake",
            type="tourist_attraction",
            description="High-altitude salt lake",
            duration_hours=3.0,
            price_range="Free",
            lat=33.7586,
            lng=78.6476,
            source="google_places",
            rating=4.6,
            review_count=1450,
            address="Pangong, Ladakh",
        )
        assert exp.rating == 4.6
        assert exp.review_count == 1450
        assert exp.address == "Pangong, Ladakh"


class TestActivityOption:
    def test_basic(self):
        place = Place(
            name="Shanti Stupa",
            description="White-domed stupa with panoramic Leh views",
            category="Monument",
            duration_minutes=60,
            price_range="Free",
            lat=34.1640,
            lng=77.5761,
            address="Changspa, Leh",
        )
        opt = ActivityOption(
            place=place,
            rank=1,
            recommendation_reason=(
                "Perfect for sunrise photography, which you listed as an interest"
            ),
            best_for=["sunrise", "photography", "panoramic views"],
            estimated_duration_minutes=60,
        )
        assert opt.rank == 1
        assert "photography" in opt.best_for

    def test_rank_must_be_positive(self):
        with pytest.raises(ValueError):
            ActivityOption(
                place=Place(
                    name="X",
                    description="X",
                    category="X",
                    duration_minutes=30,
                    price_range="Free",
                    lat=0,
                    lng=0,
                    address="X",
                ),
                rank=0,
                recommendation_reason="X",
                estimated_duration_minutes=30,
            )

    def test_advisory_fields(self):
        place = Place(
            name="Pangong Sunrise Point",
            description="Best sunrise view at Pangong Lake",
            category="Natural Feature",
            duration_minutes=90,
            price_range="Free",
            lat=33.758,
            lng=78.648,
            address="Pangong, Ladakh",
        )
        opt = ActivityOption(
            place=place,
            rank=1,
            recommendation_reason="You listed photography as a top interest",
            estimated_duration_minutes=90,
            best_time="Sunrise (5:30 AM in September)",
            crowd_warning="Crowded in peak season — arrive 30 min before dawn",
        )
        assert "Sunrise" in opt.best_time
        assert opt.crowd_warning is not None
        assert opt.booking_url is None  # default


class TestTimeSlotOptions:
    def test_defaults_empty(self):
        ts = TimeSlotOptions(slot="morning")
        assert ts.slot == "morning"
        assert ts.options == []
        assert ts.notes is None

    def test_with_two_options(self):
        def _place(name: str, lat: float, lng: float) -> Place:
            return Place(
                name=name,
                description="desc",
                category="Viewpoint",
                duration_minutes=45,
                price_range="Free",
                lat=lat,
                lng=lng,
                address=name,
            )

        ts = TimeSlotOptions(
            slot="morning",
            options=[
                ActivityOption(
                    place=_place("Shanti Stupa", 34.164, 77.576),
                    rank=1,
                    recommendation_reason="sunrise views",
                    estimated_duration_minutes=60,
                ),
                ActivityOption(
                    place=_place("Leh Palace", 34.166, 77.583),
                    rank=2,
                    recommendation_reason="history interest",
                    estimated_duration_minutes=90,
                ),
            ],
        )
        assert len(ts.options) == 2
        assert ts.options[0].rank == 1


class TestFoodOptions:
    def test_per_meal_type(self):
        venue = FoodVenue(
            name="Bon Appetit",
            category="restaurant",
            cuisine="Continental",
            price_range="₹400-700",
            rating=4.3,
            address="Fort Road, Leh",
            meal_types=["breakfast", "lunch"],
        )
        fo = FoodOptions(meal_type="breakfast", options=[venue])
        assert fo.meal_type == "breakfast"
        assert len(fo.options) == 1

    def test_remote_location_note(self):
        fo = FoodOptions(
            meal_type="dinner",
            options=[],
            notes="Very limited options in Hanle — carry packed food from Leh",
        )
        assert "Hanle" in fo.notes


class TestStayOptions:
    def test_basic(self):
        so = StayOptions(location="Nubra Valley", options=[])
        assert so.location == "Nubra Valley"
        assert so.options == []

    def test_booking_note(self):
        so = StayOptions(
            location="Pangong",
            options=[],
            notes="Tented camps fill up fast in Jul–Aug; book at least 3 weeks ahead",
        )
        assert "book" in so.notes.lower()


class TestTripSegment:
    def test_multi_day_segment(self):
        days = [
            Day(date=date(2026, 9, 1), day_number=1, location="Leh"),
            Day(date=date(2026, 9, 2), day_number=2, location="Leh"),
        ]
        seg = TripSegment(
            location="Leh",
            days=days,
            stay_options=StayOptions(location="Leh", options=[]),
            drive_notes=None,
        )
        assert len(seg.days) == 2
        assert seg.location == "Leh"
        assert seg.permits_required == []
        assert seg.altitude_meters is None

    def test_drive_notes_for_remote_segment(self):
        seg = TripSegment(
            location="Nubra Valley",
            days=[Day(date=date(2026, 9, 3), day_number=3, location="Nubra Valley")],
            drive_notes="Drive via Khardung La (5,359m) — approx 2.5h from Leh.",
        )
        assert "Khardung" in seg.drive_notes

    def test_permits_required_structured(self):
        seg = TripSegment(
            location="Pangong",
            days=[Day(date=date(2026, 9, 4), day_number=4, location="Pangong")],
            permits_required=["Inner Line Permit", "Protected Area Permit"],
            altitude_meters=4350,
        )
        assert "Inner Line Permit" in seg.permits_required
        assert seg.altitude_meters == 4350

    def test_connectivity_note(self):
        seg = TripSegment(
            location="Pangong",
            days=[Day(date=date(2026, 9, 4), day_number=4, location="Pangong")],
            connectivity="No mobile signal at Pangong. Download offline maps before leaving Leh.",
        )
        assert "offline" in seg.connectivity.lower()


class TestClarificationRequest:
    def test_required_by_default(self):
        cr = ClarificationRequest(
            field="accommodation_style",
            question="Do you prefer a hotel, guesthouse, or tented camp for Nubra?",
            context="Nubra Valley has all three — the choice affects both comfort and price.",
            suggested_options=["Hotel", "Guesthouse", "Tented camp"],
        )
        assert cr.required is True
        assert len(cr.suggested_options) == 3

    def test_optional_clarification(self):
        cr = ClarificationRequest(
            field="interests",
            question="Any specific interests? (e.g. photography, trekking, monasteries)",
            context="Defaults to popular sights if not specified.",
            required=False,
        )
        assert cr.required is False


class TestDay:
    def test_default_slots(self):
        d = Day(date=date(2026, 10, 1), day_number=1, location="Leh")
        assert d.morning.slot == "morning"
        assert d.afternoon.slot == "afternoon"
        assert d.evening.slot == "evening"
        assert d.food == []
        assert d.location == "Leh"
        assert d.altitude_warning is None

    def test_altitude_warning_on_day_one(self):
        d = Day(
            date=date(2026, 9, 1),
            day_number=1,
            location="Leh",
            altitude_warning="Acclimatization day — avoid strenuous activity. Leh sits at 3,524 m.",
        )
        assert "3,524" in d.altitude_warning


class TestItinerary:
    def test_basic(self):
        it = Itinerary(title="5 Days Ladakh", source="Delhi", destination="Ladakh", travelers=2)
        assert it.travelers == 2
        assert it.segments == []
        assert it.clarifications_needed == []
        assert it.packing_tips == []
        assert it.source_query is None
        assert it.connectivity_summary is None

    def test_ladakh_itinerary_practical_info(self):
        it = Itinerary(
            title="Ladakh Circuit",
            source="Delhi",
            destination="Ladakh",
            source_query="5 days ladakh from delhi solo trekker",
            packing_tips=["Sunscreen SPF 50+", "Warm layers", "Altitude sickness tablets"],
            connectivity_summary=(
                "BSNL works in Leh. No mobile signal in Nubra, Pangong, Hanle."
                " Download offline maps."
            ),
        )
        assert len(it.packing_tips) == 3
        assert "Leh" in it.connectivity_summary
        assert "solo" in it.source_query

    def test_multi_stop_destinations(self):
        it = Itinerary(
            title="Ladakh Circuit",
            source="Delhi",
            destination="Ladakh",
            destinations=["Leh", "Nubra Valley", "Pangong", "Hanle"],
        )
        assert len(it.destinations) == 4
        assert "Hanle" in it.destinations

    def test_clarifications_attached(self):
        it = Itinerary(
            title="Draft — needs input",
            source="Mumbai",
            destination="Spiti",
            clarifications_needed=[
                ClarificationRequest(
                    field="dates",
                    question="Which dates are you travelling?",
                    context="Needed to check road accessibility (Rohtang closes in Nov).",
                )
            ],
        )
        assert len(it.clarifications_needed) == 1
        assert it.clarifications_needed[0].field == "dates"

    def test_versioning_defaults(self):
        it = Itinerary(title="X", source="Delhi", destination="Ladakh")
        assert it.version == 1
        assert it.updated_at is None
        assert it.language_tips is None
        assert it.currency_tips is None

    def test_practical_trip_info(self):
        it = Itinerary(
            title="Ladakh Pocket Guide",
            source="Delhi",
            destination="Leh",
            language_tips="Basic Hindi useful; English widely spoken in Leh tourist areas",
            currency_tips="Carry cash — ATMs rare beyond Leh. Exchange INR before departure.",
        )
        assert "Hindi" in it.language_tips
        assert "ATM" in it.currency_tips


# ── Report models ─────────────────────────────────────────────────────────────


class TestDestinationContextReport:
    def test_valid(self):
        r = DestinationContextReport(
            destination="Osaka",
            travel_month="October",
            is_peak_season=True,
            season_label="Peak season",
            season_reason="Autumn foliage season — crowds at parks",
            crowd_level="High",
            crowd_notes="Expect queues at Osaka Castle and Dotonbori",
            real_daily_cost=8000,
            currency_code="JPY",
            seasonal_weather_summary="Cool and dry, 15–22°C",
        )
        assert r.is_peak_season is True
        assert r.crowd_level in {"Low", "Moderate", "High", "Extreme"}
        assert r.altitude_meters is None
        assert r.acclimatization_advice is None

    def test_high_altitude_destination(self):
        r = DestinationContextReport(
            destination="Leh",
            travel_month="September",
            is_peak_season=True,
            season_label="Peak season",
            season_reason="Roads open, clear skies",
            crowd_level="Moderate",
            crowd_notes="Busy but manageable",
            real_daily_cost=3000,
            currency_code="INR",
            seasonal_weather_summary="Warm days, cold nights. UV very high.",
            altitude_meters=3524,
            acclimatization_advice="Rest Day 1. Avoid alcohol. Drink 3–4L water. Diamox optional.",
        )
        assert r.altitude_meters == 3524
        assert "Diamox" in r.acclimatization_advice

    def test_negative_cost_rejected(self):
        with pytest.raises(ValueError):
            DestinationContextReport(
                destination="X",
                travel_month="Jan",
                is_peak_season=False,
                season_label="Off",
                season_reason="x",
                crowd_level="Low",
                crowd_notes="x",
                real_daily_cost=-1,
                currency_code="INR",
                seasonal_weather_summary="x",
            )


class TestScamSafetyReport:
    def test_top_scams_non_empty(self):
        r = ScamSafetyReport(
            destination="Tokyo",
            advisory_level="Exercise normal caution",
            top_scams=[
                ScamEntry(name="Bar scam", description="Overcharge", how_to_avoid="Avoid touts")
            ],
        )
        assert len(r.top_scams) >= 1


class TestVisaReport:
    def test_sources_g(self):
        r = VisaReport(
            passport_country="India",
            destination_country="Japan",
            visa_required=True,
            sources=[
                VisaSource(
                    title="MOFA Japan",
                    url="https://www.mofa.go.jp/j_info/visit/visa/index.html",
                    published_or_fetched_date="2026-06-01",
                )
            ],
            last_verified_at=datetime(2026, 6, 1, tzinfo=UTC),
            confidence="high",
        )
        assert r.sources[0].url.startswith("https://")
        assert r.last_verified_at is not None
        assert r.confidence in {"high", "medium", "low"}

    def test_default_disclaimer(self):
        r = VisaReport(
            passport_country="India", destination_country="Singapore", visa_required=False
        )
        assert "consulate" in r.disclaimer.lower()

    def test_low_confidence_no_sources(self):
        r = VisaReport(
            passport_country="India",
            destination_country="Ruritania",
            visa_required=True,
            confidence="low",
        )
        assert r.confidence == "low"
        assert r.sources == []


class TestBudgetReport:
    def test_fx_rates_used_h(self):
        r = BudgetReport(
            currency_code="JPY",
            total_estimated_cost=150000,
            fx_rates_used={
                "INR→JPY": FxRateEntry(rate=1.792, fetched_at=datetime(2026, 6, 19, tzinfo=UTC))
            },
            fx_disclaimer="Converted at interbank rate on 2026-06-19.",
            per_category_breakdown={"transport": 50000, "accommodation": 60000, "food": 40000},
            vs_budget_verdict="on-budget",
        )
        assert "INR→JPY" in r.fx_rates_used
        assert r.fx_rates_used["INR→JPY"].fetched_at is not None
        assert r.total_estimated_cost > 0

    def test_breakdown_sum_matches_total(self):
        r = BudgetReport(
            currency_code="JPY",
            total_estimated_cost=100000,
            per_category_breakdown={"transport": 40000, "accommodation": 60000},
            vs_budget_verdict="on-budget",
        )
        cat_total = sum(r.per_category_breakdown.values())
        assert abs(cat_total - r.total_estimated_cost) / r.total_estimated_cost < 0.05

    def test_per_person_and_permit_costs(self):
        r = BudgetReport(
            currency_code="INR",
            total_estimated_cost=45000,
            per_category_breakdown={"transport": 20000, "accommodation": 15000, "food": 10000},
            vs_budget_verdict="on-budget",
            per_person_cost=22500.0,
            permit_costs=1500.0,
        )
        assert r.per_person_cost == 22500.0
        assert r.permit_costs == 1500.0


class TestSelfDriveReport:
    def test_ladakh_drive_fields(self):
        r = SelfDriveReport(
            destination="Ladakh",
            recommended_vehicle="Royal Enfield 350cc",
            altitude_passes=[
                "Khardung La (5,359 m)",
                "Chang La (5,360 m)",
                "Tanglang La (5,328 m)",
            ],
            seasonal_restrictions=["Pangong route closes Nov–Apr", "Hanle accessible Jun–Sep only"],
            permits_required=["ILP from DC Office Leh", "PAP for Pangong", "PAP for Hanle"],
        )
        assert "Khardung La" in r.altitude_passes[0]
        assert len(r.seasonal_restrictions) == 2
        assert len(r.permits_required) == 3

    def test_defaults_empty(self):
        r = SelfDriveReport(destination="Goa")
        assert r.altitude_passes == []
        assert r.seasonal_restrictions == []
        assert r.permits_required == []


class TestAgentTokenUsage:
    def test_defaults_zero(self):
        u = AgentTokenUsage(agent_name="orchestrator")
        assert u.prompt_tokens == 0
        assert u.cost_usd == 0.0
