"""Pydantic models for TravelCopilot — zero business logic lives here."""

from app.models.itinerary import (
    ActivityOption as ActivityOption,
)
from app.models.itinerary import (
    ClarificationRequest as ClarificationRequest,
)
from app.models.itinerary import (
    Day as Day,
)
from app.models.itinerary import (
    Experience as Experience,
)
from app.models.itinerary import (
    FoodOptions as FoodOptions,
)
from app.models.itinerary import (
    FoodVenue as FoodVenue,
)
from app.models.itinerary import (
    Itinerary as Itinerary,
)
from app.models.itinerary import (
    OpeningHours as OpeningHours,
)
from app.models.itinerary import (
    Place as Place,
)
from app.models.itinerary import (
    StayOptions as StayOptions,
)
from app.models.itinerary import (
    TimeSlotOptions as TimeSlotOptions,
)
from app.models.itinerary import (
    TripSegment as TripSegment,
)
from app.models.reports import (
    AgentTokenUsage as AgentTokenUsage,
)
from app.models.reports import (
    ApplicationCentre as ApplicationCentre,
)
from app.models.reports import (
    BudgetReport as BudgetReport,
)
from app.models.reports import (
    DestinationContextReport as DestinationContextReport,
)
from app.models.reports import (
    FxRateEntry as FxRateEntry,
)
from app.models.reports import (
    ReviewSummary as ReviewSummary,
)
from app.models.reports import (
    ScamEntry as ScamEntry,
)
from app.models.reports import (
    ScamSafetyReport as ScamSafetyReport,
)
from app.models.reports import (
    SelfDriveReport as SelfDriveReport,
)
from app.models.reports import (
    VisaReport as VisaReport,
)
from app.models.reports import (
    VisaSource as VisaSource,
)
from app.models.transport import (
    RouteLeg as RouteLeg,
)
from app.models.transport import (
    RouteWaypoint as RouteWaypoint,
)
from app.models.transport import (
    StayOption as StayOption,
)
from app.models.transport import (
    TransportRecommendation as TransportRecommendation,
)
from app.models.user_profile import (
    BudgetPreference as BudgetPreference,
)
from app.models.user_profile import (
    BudgetTier as BudgetTier,
)
from app.models.user_profile import (
    ClarificationPrompt as ClarificationPrompt,
)
from app.models.user_profile import (
    HotelStyle as HotelStyle,
)
from app.models.user_profile import (
    TripDates as TripDates,
)
from app.models.user_profile import (
    UserProfile as UserProfile,
)
