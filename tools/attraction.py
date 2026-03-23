from typing import Annotated

import requests
from agents import function_tool
from pydantic import Field


def _pick_best_title(city: str, hits: list[dict]) -> str | None:
    city_l = city.lower().strip()
    best_title = None
    best_score = -10
    for item in hits:
        title = str(item.get("title", "")).strip()
        snippet = str(item.get("snippet", "")).lower()
        title_l = title.lower()
        if not title:
            continue

        score = 0
        if city_l and city_l in title_l:
            score += 4
        if city_l and city_l in snippet:
            score += 2
        if any(k in title_l for k in ["attraction", "tourism", "travel", "landmark", "guide"]):
            score += 1
        if "disambiguation" in snippet:
            score -= 3

        if score > best_score:
            best_score = score
            best_title = title
    return best_title


@function_tool
async def search_attractions(
    city: Annotated[str, Field(description="要搜索的城市名称")]
) -> str:
    """搜索城市的著名旅游景点、地标和文化背景信息。"""
    headers = {"User-Agent": "TravelPlannerAgent/1.0"}

    try:
        search = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "list": "search",
                "srsearch": f"{city} (tourist attractions OR landmarks OR travel guide)",
                "srlimit": 6,
                "format": "json",
            },
            headers=headers,
            timeout=10,
        )
    except Exception as exc:
        return f"景点检索失败：{exc}"

    hits = []
    if search.status_code == 200:
        try:
            hits = search.json().get("query", {}).get("search", [])
        except Exception:
            hits = []
    title = _pick_best_title(city, hits) or city

    try:
        summary = requests.get(
            f"https://en.wikipedia.org/api/rest_v1/page/summary/{requests.utils.quote(title)}",
            headers=headers,
            timeout=10,
        )
    except Exception as exc:
        return f"景点摘要获取失败：{exc}"

    if summary.status_code == 200:
        extract = summary.json().get("extract", "")
        if extract:
            return f"**{title}**\n\n{extract[:1200]}"

    return f"未能获取 {city} 的景点资料，请根据已有知识规划行程。"
