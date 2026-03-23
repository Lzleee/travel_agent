import json
import os
from typing import Generator

import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")


def stream_from_backend(message: str, session_id: str | None) -> Generator[dict, None, None]:
    with requests.post(
        f"{BACKEND_URL}/chat",
        json={"message": message, "session_id": session_id},
        stream=True,
        timeout=120,
    ) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines():
            if line and line.startswith(b"data: "):
                yield json.loads(line[6:])


def run_chat(user_message: str) -> str:
    status_box = st.empty()
    text_box = st.empty()
    result = ""

    for event in stream_from_backend(user_message, st.session_state.get("session_id")):
        etype = event.get("type")
        if etype == "session_id":
            st.session_state.session_id = event["session_id"]
        elif etype == "tool_start":
            label = event.get("label", event.get("name", "工具调用"))
            status_box.info(f"🔍 {label}...")
        elif etype == "content":
            result += event.get("text", "")
            text_box.markdown(result + "▌")
        elif etype == "done":
            break

    status_box.empty()
    text_box.markdown(result)
    return result
