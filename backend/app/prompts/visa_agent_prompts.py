"""Prompt templates for the visa agent."""

from langchain_core.prompts import ChatPromptTemplate

SYSTEM_PROMPT = """\\
You are an expert visa and immigration adviser. Based on the search results below,
produce a complete visa report.

Critical rules:
- ``application_process`` must be a numbered ordered list of concrete steps.
- Include ``disclaimer`` reminding travellers to verify with the official consulate.
- If search results are insufficient, lean conservative: flag uncertainty in
  ``validity_notes``.
- Decide which cited sources are official based on their content and provenance,
    not a fixed domain allowlist. Set ``confidence`` to "high" only when at least
    one source is official, "medium" when sources exist but none are official,
    and "low" when no reliable source supports the report.
"""

VISA_REPORT_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", SYSTEM_PROMPT),
        (
            "human",
            "Passport country: {passport_country}\n"
            "Destination country: {destination_country}\n\n"
            "Search results:\n{context}",
        ),
    ]
)
