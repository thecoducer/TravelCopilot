from app.services.trip_stream_service import agent_preview


def test_agent_preview_counts_multi_stop_stays() -> None:
    output = {
        "stays_raw_by_stop": {
            "stop_1": [{"name": "Stay one"}, {"name": "Stay two"}],
            "stop_2": [{"name": "Stay three"}],
        }
    }

    assert agent_preview("stay_search", output) == "Found 3 places to stay"


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

    assert agent_preview("transport_search", output) == "Found 3 route legs"


def test_agent_preview_describes_empty_results_without_a_zero_count() -> None:
    assert agent_preview("stay_search", {"stays_raw": []}) == "No places to stay found"


def test_agent_preview_counts_flat_shortlist() -> None:
    output = {"stays_shortlist": [{"name": "Stay one"}]}

    assert agent_preview("stay_analyst", output) == "Found 1 shortlisted stay"
