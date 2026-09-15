"""Unit tests for the username-identity, session, and photo helpers."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.agents.reviews_agent import _photo_urls
from app.agents.stay_search_agent import _hotel_photo_urls
from app.models.trip import PlanRequest
from app.models.user_profile import UserProfile
from app.routers.user import _validate_username
from app.services.trip_service import _derive_title


class _StubItinerary:
    def __init__(self, title: str) -> None:
        self.title = title


class TestDeriveTitle:
    def test_prefers_itinerary_title(self) -> None:
        result = _derive_title(_StubItinerary("7 Days in Kyoto"), "plan me a trip")
        assert result == "7 Days in Kyoto"

    def test_falls_back_to_query_when_no_title(self) -> None:
        assert _derive_title(None, "Weekend in Goa") == "Weekend in Goa"

    def test_truncates_long_query(self) -> None:
        title = _derive_title(None, "x" * 100)
        assert title.endswith("…")
        assert len(title) == 61

    def test_empty_query_defaults(self) -> None:
        assert _derive_title(None, "   ") == "New trip"


class TestValidateUsername:
    @pytest.mark.parametrize("username", ["alice", "bob_42", "a-b-c", "User_Name-1"])
    def test_accepts_valid(self, username: str) -> None:
        assert _validate_username(f"  {username}  ") == username

    @pytest.mark.parametrize("username", ["ab", "x" * 33, "has space", "bad!char", ""])
    def test_rejects_invalid(self, username: str) -> None:
        with pytest.raises(HTTPException) as exc:
            _validate_username(username)
        assert exc.value.status_code == 422


class TestPhotoHelpers:
    def test_hotel_photos_prefer_original_image(self) -> None:
        images = [{"thumbnail": "http://t/1.jpg", "original_image": "http://o/1.jpg"}]
        assert _hotel_photo_urls(images) == ["http://o/1.jpg"]

    def test_hotel_photos_fall_back_to_thumbnail(self) -> None:
        assert _hotel_photo_urls([{"thumbnail": "http://t/2.jpg"}]) == ["http://t/2.jpg"]

    def test_hotel_photos_accept_plain_strings(self) -> None:
        assert _hotel_photo_urls(["http://x/3.jpg"]) == ["http://x/3.jpg"]

    def test_review_photos_drop_resource_dicts(self) -> None:
        raw = [{"name": "places/x/photos/y"}, "http://ok/z.jpg", "not-a-url"]
        assert _photo_urls(raw) == ["http://ok/z.jpg"]


class TestModelExtensions:
    def test_user_profile_has_username_and_budget(self) -> None:
        profile = UserProfile(user_id="u", username="alice", total_budget=1500, per_day_budget=200)
        assert profile.username == "alice"
        assert profile.total_budget == 1500
        assert profile.per_day_budget == 200

    def test_plan_request_defaults_to_new_mode(self) -> None:
        assert PlanRequest(query="a trip please").mode == "new"

    def test_plan_request_accepts_followup(self) -> None:
        request = PlanRequest(query="add a day", username="alice", mode="followup")
        assert request.mode == "followup"
        assert request.username == "alice"
