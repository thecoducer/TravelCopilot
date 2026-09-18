"""Currency resolution: the trip currency comes from the profile, never a hardcoded default."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.stay_search_agent import StaySearchAgent
from app.config import settings
from app.models.user_profile import UserProfile
from app.services.currency_service import resolve_from_state, resolve_trip_currency


class TestResolveTripCurrency:
    def test_uses_profile_preference(self) -> None:
        profile = UserProfile(user_id="u1", preferred_currency="JPY")
        assert resolve_trip_currency(profile) == "JPY"

    def test_normalises_case(self) -> None:
        profile = UserProfile(user_id="u1", preferred_currency="eur")
        assert resolve_trip_currency(profile) == "EUR"

    def test_falls_back_to_configured_default(self) -> None:
        assert resolve_trip_currency(None) == settings.default_currency.upper()

    def test_rejects_malformed_code(self) -> None:
        profile = UserProfile(user_id="u1", preferred_currency="rupees")
        assert resolve_trip_currency(profile) == settings.default_currency.upper()

    def test_resolves_from_graph_state(self) -> None:
        state = {"user_profile": UserProfile(user_id="u1", preferred_currency="GBP")}
        assert resolve_from_state(state) == "GBP"


class TestStaySearchCurrency:
    @pytest.mark.asyncio
    async def test_hotels_are_searched_in_the_profile_currency(self) -> None:
        hotel_tool = MagicMock()
        hotel_tool.run = AsyncMock(return_value={"properties": []})
        factory = MagicMock()
        factory.get = MagicMock(return_value=hotel_tool)

        agent = StaySearchAgent(tool_factory=factory)
        await agent(
            {
                "destination": "Kochi",
                "travelers": 2,
                "user_profile": UserProfile(user_id="u1", preferred_currency="INR"),
                "session_id": "s1",
            }
        )

        assert hotel_tool.run.await_args.kwargs["currency"] == "INR"

    @pytest.mark.asyncio
    async def test_price_currency_follows_the_requested_currency(self) -> None:
        """A provider price with no explicit code is denominated in what we asked for."""
        hotel_tool = MagicMock()
        hotel_tool.run = AsyncMock(
            return_value={
                "properties": [
                    {
                        "name": "Napier Heritage",
                        "rate_per_night": {"lowest": "5,400"},
                        "overall_rating": 4.6,
                        "reviews": 1343,
                    }
                ]
            }
        )
        factory = MagicMock()
        factory.get = MagicMock(return_value=hotel_tool)

        agent = StaySearchAgent(tool_factory=factory)
        result = await agent(
            {
                "destination": "Kochi",
                "travelers": 2,
                "user_profile": UserProfile(user_id="u1", preferred_currency="INR"),
                "session_id": "s1",
            }
        )

        stays = result["stays_raw"]
        assert stays, "expected the property to be parsed"
        assert stays[0].currency_code == "INR"
        assert stays[0].price_per_night == 5400.0
