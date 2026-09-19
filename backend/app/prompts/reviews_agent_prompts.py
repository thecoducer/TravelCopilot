"""Prompt templates for the reviews agent."""

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from app.models.enums import Sentiment

JUDGEABLE_SENTIMENTS = (Sentiment.POSITIVE, Sentiment.MIXED, Sentiment.NEGATIVE)

SYSTEM_PROMPT = f"""\
You are a travel reviewer. Given the raw place details and reviews below, synthesise a
concise reviewer summary for a traveller.

Rules:
- ``pros`` should list 2–4 concrete positives mentioned by multiple reviewers.
- ``cons`` should list 1–3 genuine negatives (skip if the place has near-perfect reviews).
- ``sentiment`` must be one of: {" | ".join(JUDGEABLE_SENTIMENTS)}.
- Keep each pro/con to a single short sentence.
"""

REVIEW_SUMMARY_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", SYSTEM_PROMPT),
        (
            "human",
            "Place: {place_name}\n"
            "Rating: {rating}/5 ({review_count} reviews)\n\n"
            "Reviews:",
        ),
        MessagesPlaceholder("reviews"),
    ]
)
