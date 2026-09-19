"""Prompt templates for shared agent behavior."""

from langchain_core.prompts import ChatPromptTemplate

OPTIONAL_CLARIFICATION_SYSTEM_PROMPT = (
    "You may ask up to 3 optional questions to improve the itinerary. "
    "Use field names beginning with optional_. Ask only for useful, "
    "trip-scoped preferences. Never ask for required fields, credentials, "
    "or sensitive personal data. Return an empty prompts list when no "
    "question is useful. Every prompt must be optional=true."
)

OPTIONAL_CLARIFICATION_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", OPTIONAL_CLARIFICATION_SYSTEM_PROMPT),
        ("human", "Agent context:\n{context}\nTrip state:\n{state}"),
    ]
)
