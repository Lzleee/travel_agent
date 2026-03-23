import json
import os
from typing import AsyncGenerator
from uuid import uuid4

from agents import Runner, set_default_openai_client
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from openai import AsyncOpenAI
from openai.types.responses import ResponseTextDeltaEvent
from pydantic import BaseModel

from agent.sdk_agent import travel_agent
from utils.logging import dump_item, extract_tool_arguments, extract_tool_output, setup_app_logger, truncate_for_log
from memory.llm_summarizer import LLMSummarizer
from memory.store import ConversationMemoryStore

load_dotenv()

LOG_FILE_PATH = os.getenv("AGENT_LOG_FILE", "agent.log")
TOOL_LOG_MAX_CHARS = int(os.getenv("AGENT_TOOL_LOG_MAX_CHARS", "4000"))
logger = setup_app_logger(LOG_FILE_PATH)

MAX_TURNS = int(os.getenv("AGENT_MAX_TURNS", "8"))
MEMORY_DB_PATH = os.getenv("AGENT_MEMORY_DB", "storage/memory.sqlite")
MEMORY_RECENT_TURNS = int(os.getenv("AGENT_MEMORY_RECENT_TURNS", "4"))
MEMORY_SUMMARY_MAX_CHARS = int(os.getenv("AGENT_MEMORY_SUMMARY_MAX_CHARS", "3000"))
MEMORY_ITEM_MAX_CHARS = int(os.getenv("AGENT_MEMORY_ITEM_MAX_CHARS", "220"))
MEMORY_USE_LLM_SUMMARY = os.getenv("AGENT_MEMORY_USE_LLM_SUMMARY", "1").strip() not in {"0", "false", "False"}
MEMORY_SUMMARY_MODEL = os.getenv("AGENT_MEMORY_SUMMARY_MODEL", os.getenv("OPENAI_MODEL", "gpt-5.2"))
MEMORY_SUMMARY_MAX_TOKENS = int(os.getenv("AGENT_MEMORY_SUMMARY_MAX_TOKENS", "320"))

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")

if OPENAI_BASE_URL:
    custom_client = AsyncOpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)
    set_default_openai_client(custom_client)

app = FastAPI(title="Travel Agent API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

TOOL_LABELS = {
    "get_weather": "正在查询天气预报",
    "search_attractions": "正在搜索景点信息",
    "search_places_google": "正在通过 Google 地图搜索地点",
    "get_route_google": "正在通过 Google 地图计算通勤",
}

llm_summarizer = LLMSummarizer(
    api_key=OPENAI_API_KEY,
    base_url=OPENAI_BASE_URL,
    model=MEMORY_SUMMARY_MODEL,
    max_output_tokens=MEMORY_SUMMARY_MAX_TOKENS,
    enabled=MEMORY_USE_LLM_SUMMARY,
)


memory_store = ConversationMemoryStore(
    db_path=MEMORY_DB_PATH,
    recent_turns=MEMORY_RECENT_TURNS,
    summary_max_chars=MEMORY_SUMMARY_MAX_CHARS,
    item_max_chars=MEMORY_ITEM_MAX_CHARS,
    llm_summarizer=llm_summarizer,
)
memory_store.init_db()


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


def sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def extract_tool_name(item) -> str | None:
    raw_item = getattr(item, "raw_item", None)
    if not raw_item:
        return None
    if isinstance(raw_item, dict):
        return raw_item.get("name") or raw_item.get("tool_name")
    return getattr(raw_item, "name", None) or getattr(raw_item, "tool_name", None)


async def stream_agent(message: str, session_id: str | None) -> AsyncGenerator[str, None]:
    sid = session_id or uuid4().hex
    logger.info("[Session] id=%s", sid)
    logger.info("[Request] sid=%s message=%s", sid, message)
    yield sse({"type": "session_id", "session_id": sid})

    assistant_reply = ""
    try:
        memory_store.compact_session_history(sid)
        model_input = memory_store.build_input_messages(sid, message)
        logger.info("[ModelInput] sid=%s payload=%s", sid, json.dumps(model_input, ensure_ascii=False))
        result = Runner.run_streamed(
            travel_agent,
            input=model_input,
            max_turns=MAX_TURNS,
        )

        async for event in result.stream_events():
            if event.type == "raw_response_event" and isinstance(event.data, ResponseTextDeltaEvent):
                delta = event.data.delta or ""
                if delta:
                    assistant_reply += delta
                    yield sse({"type": "content", "text": delta})
            elif event.type == "run_item_stream_event":
                item = event.item
                if item.type == "tool_call_item":
                    tool_name = extract_tool_name(item) or "tool_call"
                    label = TOOL_LABELS.get(tool_name, tool_name)
                    args = extract_tool_arguments(item) or ""
                    logger.info(
                        "[Tool] sid=%s name=%s args=%s",
                        sid,
                        tool_name,
                        truncate_for_log(args, TOOL_LOG_MAX_CHARS),
                    )
                    if not args:
                        logger.info(
                            "[ToolRaw] sid=%s name=%s raw=%s",
                            sid,
                            tool_name,
                            truncate_for_log(dump_item(item), TOOL_LOG_MAX_CHARS),
                        )
                    yield sse({"type": "tool_start", "name": tool_name, "label": label})
                elif item.type in {"tool_call_output_item", "tool_result_item"}:
                    output = extract_tool_output(item) or ""
                    logger.info(
                        "[ToolOutput] sid=%s item_type=%s payload=%s",
                        sid,
                        item.type,
                        truncate_for_log(output, TOOL_LOG_MAX_CHARS),
                    )
                else:
                    logger.info("[RunItem] sid=%s item_type=%s", sid, item.type)
        final_reply = assistant_reply.strip()
        memory_store.append_turn(sid, message, final_reply)
        logger.info("[Response] sid=%s message=%s", sid, final_reply)
    except Exception as exc:  # pragma: no cover - defensive guard for streaming errors
        logger.exception("[Error] sid=%s Agent run failed: %s", sid, exc)
        fallback = "抱歉，行程规划服务暂时不可用，请稍后再试。"
        memory_store.append_turn(sid, message, fallback)
        logger.info("[Response] sid=%s message=%s", sid, fallback)
        yield sse({"type": "content", "text": fallback})
    finally:
        logger.info("[Done] sid=%s", sid)
        yield sse({"type": "done"})


@app.post("/chat")
async def chat(request: ChatRequest):
    logger.info("[HTTP] POST /chat session_id=%s", request.session_id)
    return StreamingResponse(
        stream_agent(request.message, request.session_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/health")
async def health():
    return {"status": "ok"}
