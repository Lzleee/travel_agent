import streamlit as st

from chat_client import BACKEND_URL, run_chat
from map_view import render_places_map
from sidebar import render_sidebar


st.set_page_config(page_title="智能旅行规划", page_icon="✈️", layout="wide")
st.title("✈️ 智能旅行规划助手")
st.caption(f"后端：`{BACKEND_URL}`")

render_sidebar()

if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg["role"] == "assistant":
            render_places_map(msg["content"])

if st.session_state.get("pending"):
    st.session_state.pending = False
    with st.chat_message("assistant"):
        reply = run_chat(st.session_state.messages[-1]["content"])
        render_places_map(reply)
    st.session_state.messages.append({"role": "assistant", "content": reply})

if user_input := st.chat_input("继续对话，例如：把第二天改成海边活动…"):
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)
    with st.chat_message("assistant"):
        reply = run_chat(user_input)
        render_places_map(reply)
    st.session_state.messages.append({"role": "assistant", "content": reply})
