"""Prompt templates for the budget planner agent."""

from langchain_core.prompts import ChatPromptTemplate

SYSTEM_PROMPT = """\\
You are a travel budget analyst and cost estimator with deep knowledge of global pricing.
Given a travel destination, budget tier, and trip parameters, estimate realistic daily food and \\
activity costs.

Rules:
- Estimates MUST be in the destination's local currency.
- ``daily_food_per_person``: Average daily spending per person for meals, drinks, and dining.
- ``daily_activity_per_person``: Average daily spending per person for entry fees and tours.
"""

COST_SAVING_TIPS_SYSTEM_PROMPT = "You are a budget travel advisor."

COST_ESTIMATE_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", SYSTEM_PROMPT),
        (
            "human",
            "Destination: {destination}\n"
            "Destination Currency: {dest_currency}\n"
            "Budget Tier: {tier}\n"
            "Travelers: {travelers}, Trip Duration: {trip_days} days\n"
            "Discovered Food Venues: {food_names}\n"
            "Discovered Activities: {exp_names}\n"
            "Estimate realistic daily per-person food and activity costs for "
            "{destination} in {dest_currency} matching the '{tier}' budget tier.",
        ),
    ]
)

COST_SAVING_TIPS_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", COST_SAVING_TIPS_SYSTEM_PROMPT),
        (
            "human",
            "Trip to {destination}, {trip_days} days, {travelers} travelers.\n"
            "Budget tier: {tier}. Currently over budget.\n"
            "Cost breakdown: {cost_breakdown}\n\n"
            "Provide 3–5 specific, actionable cost-saving tips.",
        ),
    ]
)
