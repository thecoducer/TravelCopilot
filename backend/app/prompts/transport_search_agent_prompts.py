"""Prompt templates for the transport search agent."""

from langchain_core.prompts import ChatPromptTemplate

HUB_SYSTEM_PROMPT = """\\
You are a transport routing expert. Given a source and destination, identify all
plausible route combinations a traveller might take.

For each route combination return:
  - origin: IATA code or city name
  - destination: IATA code or city name
  - mode: "flight" | "train" | "bus" | "cab" | "taxi" | "ferry" | "other"
  - via_hub: intermediate city/IATA code (if applicable)

Return between 1 and 5 route combinations — prefer direct routes first, then
1-stop via major hubs. For domestic Indian routes always include a train option
where relevant.
"""

HUB_DISCOVERY_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", HUB_SYSTEM_PROMPT),
        ("human", "Source: {source}\nDestination: {destination}"),
    ]
)
