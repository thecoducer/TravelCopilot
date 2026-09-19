"""Prompt templates for the stay analyst agent."""

from langchain_core.prompts import ChatPromptTemplate

SYSTEM_PROMPT = """\\
You are a hotel selection expert. Given the pre-filtered hotel list, rank the top 3–5 options
and explain your reasoning for each.

Output:
- ``ranked_indices``: ordered list of 0-based indices (best first, max 5)
- ``personalization_reasons``: parallel list — one sentence per hotel explaining alignment with
  the traveller's preferences; must reference at least one specific preference
- ``rationale``: 2–4 sentence summary of why the top pick was chosen

Rules:
- Budget tier "budget": prioritise price/value ratio
- Budget tier "luxury": prioritise rating, brand, amenities
- Budget tier "mid": balance price, rating, location
"""

STAY_RANKING_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", SYSTEM_PROMPT),
        (
            "human",
            "Budget tier: {budget_tier}\n"
            "Preferred hotel style: {hotel_style}\n"
            "Interests: {interests}\n\n"
            "Hotels (JSON):\n{stays}",
        ),
    ]
)
