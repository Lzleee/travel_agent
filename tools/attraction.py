from typing import Annotated

import requests
from agents import function_tool
from pydantic import Field

@function_tool
async def search_attractions(
    city: Annotated[str, Field(description="要搜索的城市名称")]
) -> str:
    """搜索城市的著名旅游景点、地标和文化背景信息。"""
    headers = {"User-Agent": "TravelPlannerAgent/1.0"}

    search = requests.get(
        "https://en.wikipedia.org/w/api.php",
        params={
            "action": "query",
            "list": "search",
            "srsearch": f"{city} tourism attractions",
            "srlimit": 1,
            "format": "json",
        },
        headers=headers,
        timeout=10,
    )
    hits = search.json().get("query", {}).get("search", []) if search.status_code == 200 else []
    title = hits[0]["title"] if hits else city

    summary = requests.get(
        f"https://en.wikipedia.org/api/rest_v1/page/summary/{requests.utils.quote(title)}",
        headers=headers,
        timeout=10,
    )
    if summary.status_code == 200:
        extract = summary.json().get("extract", "")
        if extract:
            return f"**{title}**\n\n{extract[:1200]}"

    return f"未能获取 {city} 的景点资料，请根据已有知识规划行程。"
