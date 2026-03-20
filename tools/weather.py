from typing import Annotated

import requests
from agents import function_tool
from pydantic import Field

WMO_CODES = {
    0: "晴", 1: "基本晴朗", 2: "局部多云", 3: "阴天",
    45: "雾", 48: "雾凇",
    51: "小毛毛雨", 53: "毛毛雨", 55: "大毛毛雨",
    61: "小雨", 63: "中雨", 65: "大雨",
    71: "小雪", 73: "中雪", 75: "大雪",
    80: "阵雨", 81: "中等阵雨", 82: "大阵雨",
    95: "雷暴", 96: "雷暴伴冰雹", 99: "强雷暴",
}


@function_tool
async def get_weather(
    city: Annotated[str, Field(description="要查询的城市名称")]
) -> str:
    """查询城市未来5天的天气预报，包括温度区间和降水概率。"""

    geo = requests.get(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": city, "count": 1, "language": "zh", "format": "json"},
        timeout=10,
    )
    results = geo.json().get("results") if geo.status_code == 200 else None
    if not results:
        return f"找不到城市“{city}”，请检查拼写。"

    loc = results[0]
    lat, lon, name = loc["latitude"], loc["longitude"], loc.get("name", city)

    weather = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lat,
            "longitude": lon,
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weathercode",
            "timezone": "auto",
            "forecast_days": 5,
        },
        timeout=10,
    )
    if weather.status_code != 200:
        return "天气数据获取失败，请稍后重试。"

    daily = weather.json()["daily"]
    lines = [f"**{name} 未来5天天气预报**"]
    for i, date in enumerate(daily["time"]):
        tmax = daily["temperature_2m_max"][i]
        tmin = daily["temperature_2m_min"][i]
        rain = daily["precipitation_probability_max"][i]
        desc = WMO_CODES.get(daily["weathercode"][i], "未知")
        lines.append(f"- {date}：{desc}，{tmin}°C ~ {tmax}°C，降水概率 {rain}%")

    return "\n".join(lines)
