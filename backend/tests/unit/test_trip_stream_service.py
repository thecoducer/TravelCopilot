from app.services.trip_stream_service import agent_preview


def test_agent_preview_counts_multi_stop_stays() -> None:
    output = {
        "stays_raw_by_stop": {
            "stop_1": [{"name": "Stay one"}, {"name": "Stay two"}],
            "stop_2": [{"name": "Stay three"}],
        }
    }

    assert agent_preview("stay_search", output) == "Found 3 hotels"


def test_agent_preview_counts_multi_stop_experiences() -> None:
    output = {"experiences_raw_by_stop": {"stop_1": [{"name": "Museum"}]}}

    assert agent_preview("local_experiences", output) == "Found 1 experience"


def test_agent_preview_counts_multi_leg_transport() -> None:
    output = {
        "transport_legs_raw_by_leg": {
            "leg_1": [{"mode": "flight"}, {"mode": "train"}],
            "leg_2": [{"mode": "bus"}],
        }
    }

    assert agent_preview("transport_search", output) == "Found 3 transport options"


def test_agent_preview_describes_empty_results_without_a_zero_count() -> None:
    assert agent_preview("stay_search", {"stays_raw": []}) == "No hotels found"


def test_agent_preview_counts_flat_shortlist() -> None:
    output = {"stays_shortlist": [{"name": "Stay one"}]}

    assert agent_preview("stay_analyst", output) == "Found 1 shortlisted stay"


def test_orchestrator_preview_hides_arrow_until_both_route_endpoints_exist() -> None:
    assert agent_preview("orchestrator", {"source": "Kolkata"}) == "Kolkata"
    assert agent_preview("orchestrator", {"destination": "Goa"}) == "Goa"
    assert agent_preview("orchestrator", {}) == "Extracting trip details"
    assert agent_preview(
        "orchestrator", {"source": "Kolkata", "destination": "Goa"}
    ) == "Kolkata → Goa"


def test_agent_preview_covers_report_and_summary_outputs() -> None:
    assert agent_preview(
        "safety", {"safety_report": {"top_scams": [{"name": "Taxi scam"}]}}
    ) == "1 scams found"
    assert agent_preview(
        "visa", {"visa_report": {"visa_required": False}}
    ) == "Visa required: False"
    assert agent_preview(
        "self_drive_search",
        {"self_drive_report": {"rental_options": [{"name": "Car"}, {"name": "Bike"}]}},
    ) == "Found 2 rental options"
    assert agent_preview(
        "reviews", {"reviews_summary": {"stay-1": {}, "stay-2": {}}}
    ) == "Found 2 review summaries"


def test_agent_preview_counts_nested_food_recommendations() -> None:
    output = {
        "food_recommendations_by_stop": {
            "stop_1": {
                "2026-11-11": [{"meal_type": "breakfast"}, {"meal_type": "lunch"}]
            }
        }
    }

    assert agent_preview("food_discovery", output) == "Found 2 food recommendations"


def test_agent_preview_reads_dictionary_shaped_model_outputs() -> None:
    assert agent_preview(
        "transport_optimizer",
        {"transport_recommendation": {"rationale": "Fastest direct route"}},
    ) == "Fastest direct route"
    assert agent_preview(
        "budget_planner",
        {"budget_report": {"total_estimated_cost": 16360, "vs_budget_verdict": "on-budget"}},
    ) == "16360 (on-budget)"
    assert agent_preview(
        "itinerary_compiler", {"itinerary": {"title": "Goa escape"}}
    ) == "Goa escape"
