import os

from agents import Agent
from dotenv import load_dotenv

from agent.prompts import SYSTEM_PROMPT
from tools.weather import get_weather
from tools.attraction import search_attractions
from tools.map import get_route_google, search_places_google

load_dotenv()

DEFAULT_OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.2")

travel_agent = Agent(
    name="TravelPlanner",
    instructions=SYSTEM_PROMPT,
    model=DEFAULT_OPENAI_MODEL,
    tools=[get_weather, search_attractions, search_places_google, get_route_google],
)
