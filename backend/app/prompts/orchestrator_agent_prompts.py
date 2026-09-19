"""Prompt templates and clarification catalogues for the orchestrator agent."""

from typing import Any

from langchain_core.prompts import ChatPromptTemplate

from app.models.clarification import ClarificationPrompt

FIELD_META: dict[str, dict[str, Any]] = {
    "destination": {
        "input_type": "text",
        "options": [],
        "generic": "Where would you like to travel? Please name the city or region.",
        "contextual": "You mentioned '{value}' — which city or region specifically?",
    },
    "dates": {
        "input_type": "date",
        "options": [],
        "generic": "What is the start date of your trip?",
        "contextual": "When would you like to start your trip to '{value}'?",
    },
    "travelers": {
        "input_type": "number",
        "options": [],
        "generic": "How many people are travelling?",
        "contextual": "How many people will be going on the trip?",
    },
    "trip_days": {
        "input_type": "number",
        "options": [],
        "generic": "How many days is your trip?",
        "contextual": "You mentioned '{value}' days — is that the total length of your trip?",
    },
    "budget": {
        "input_type": "select",
        "options": ["budget", "mid", "luxury"],
        "generic": "What is your budget preference: budget, mid-range, or luxury?",
        "contextual": "You mentioned a {value} budget — is that right?",
    },
    "source": {
        "input_type": "text",
        "options": [],
        "generic": "What city will you be departing from?",
        "contextual": "Please provide the departure city.",
    },
    "query": {
        "input_type": "text",
        "options": [],
        "generic": (
            "Could you describe your trip in more detail?"
            " (e.g. 'I want to go to Leh from Kolkata for 5 days in July')"
        ),
        "contextual": "Could you describe your trip in more detail?",
    },
}

OPTIONAL_CLARIFICATION_PROMPTS: tuple[ClarificationPrompt, ...] = (
    ClarificationPrompt(
        field="optional_pace",
        question="What pace would you like for this trip?",
        reason="Controls how many activities are scheduled per day",
        input_type="select",
        options=["relaxed", "balanced", "packed"],
        optional=True,
    ),
    ClarificationPrompt(
        field="optional_travel_style",
        question="Which travel style best describes this trip?",
        reason="Shapes stay and experience recommendations",
        input_type="select",
        options=["adventure", "cultural", "family", "backpacker", "luxury"],
        optional=True,
    ),
    ClarificationPrompt(
        field="optional_must_see",
        question="Anything you absolutely want to include?",
        reason="Guarantees a must-see place makes the itinerary",
        input_type="text",
        optional=True,
    ),
)

FOOD_CLARIFICATION_PROMPTS: tuple[ClarificationPrompt, ...] = (
    ClarificationPrompt(
        field="preferred_cuisines",
        question="Which cuisines would you most like to eat on this trip?",
        reason="Personalize restaurant discovery",
        input_type="text",
        optional=True,
    ),
    ClarificationPrompt(
        field="dietary_restrictions",
        question="Do you have dietary restrictions or requirements?",
        reason="Avoid unsuitable restaurant recommendations",
        input_type="text",
        options=["No dietary restrictions"],
        optional=True,
    ),
)

SYSTEM_PROMPT = """\\
You are a travel query parser. Extract structured fields from the user's trip request.
For each field that has ambiguity, set a lower confidence score.

Rules:
- source: return only the departure city name from phrases such as "from Kolkata", "departing from Mumbai", or "starting in Delhi". Do not include the state, region, or country. Return null with confidence=0.0 when no departure city is provided. If the city is ambiguous, lower its confidence and ask the user to clarify the city.
- destination: extract the complete requested place and its stated geographic context from phrases such as "to Arunachal Pradesh, India", "visit Tokyo, Japan", or "trip in Goa, India". Preserve the city, state/region, and country when provided. Return null with confidence=0.0 when no destination is provided.
- If the departure date is relative (e.g. "next month"), resolve to ISO-8601 assuming today is {today}.
- If no date is mentioned at all, set departure_date=null and dates_confidence=0.0.
- departure_date: extract the start date. return_date: extract an explicitly stated end or return date from phrases such as "returning on November 15", "until November 15", or "from November 11 to November 15". Resolve relative dates using today={today}, normalize both dates to ISO-8601, and set return_date=null when no return/end date is specified.
- trip_days: extract the duration of the trip in days (e.g. "sixteen days" -> "16", "6 days" -> 6, "10-day trip" -> 10, "1 week" -> 7, "weekend" -> 2). Convert number words to integers. If no duration is mentioned or implied at all, set trip_days=null and trip_days_confidence=0.0 — never guess a number.
- is_international: identify the country for both source and destination, including when a place is a state, region, or landmark. Set true when the trip crosses country borders (for example, "Kolkata to Tokyo", "New York to Paris", or "India to Bhutan"). Set false when both locations are in the same country (for example, "Kolkata to Goa" or "Mumbai to Ladakh"). Do not treat a region or destination name alone as international; use the source and destination together. Return null when either country cannot be determined reliably; do not guess domestic or international status.
- source_country / destination_country: always return the full English country name for each place when it can be identified from the place itself (for example, source="Kolkata" -> source_country="India"; destination="Sikkim" -> destination_country="India"; destination="Tokyo" -> destination_country="Japan"). Resolve states, regions, and landmarks to their country. Return null only when the place is genuinely absent or too ambiguous to place in a country.
- self_drive_intent: set true when the traveller wants to drive themselves or arrange a vehicle for the trip, including phrases such as "rent a car", "hire a scooter", "drive from Delhi to Manali", "road trip", "self-drive", "use our own car", or "motorbike trip". Set false for ordinary transport requests such as flights, trains, buses, taxis, or airport transfers when the traveller is not driving. Do not infer self-drive only from a destination being remote or scenic.
- budget_tier: extract an explicit budget preference only. Use "budget" for hostel/cheapest/backpacker, "luxury" for five-star/premium, and "mid" for mid-range/standard. If no preference is stated, return null; never assume "mid".
- For interests, extract: food, nightlife, history, adventure, photography, wellness, nature, art.
- Confidence rules (dates_confidence, trip_days_confidence): 1.0 = explicitly stated; 0.7 = strongly implied; 0.5 = inferred; 0.0 = absent.
- For travelers: confidence=1.0 for explicit phrases such as "2 people", "three people", "2 travelers", "three travelers", "there are 2 of us", "we are 2", or "a group of three". Convert number words to integers. If no traveler count is stated, return value=null and confidence=0.0; never assume one traveler.

Examples:
- "Plan 5 days in Tokyo from Kolkata" -> is_international=true, self_drive_intent=false.
- "Plan a trip to Darjeeling for 5 days for three people" -> travelers.value="3", travelers.confidence=1.0.
- "Plan a road trip from Mumbai to Goa in our own car" -> is_international=false, self_drive_intent=true.
- "Fly from Delhi to London and take trains between cities" -> is_international=true, self_drive_intent=false.
- "Rent a scooter in Goa" -> is_international=false, self_drive_intent=true.
- "Plan a trip from Springfield to Paris" -> is_international=null if the source country is not specified and Springfield is ambiguous.
"""  # noqa: E501

QUERY_PARSE_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", SYSTEM_PROMPT),
        ("human", "User query: {query}"),
    ]
)
