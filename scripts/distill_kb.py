#!/usr/bin/env python3
"""
Distill a travel RAG knowledge base from real sources.

This script turns:
1) Local documents (txt/md/html) or
2) Conversation logs in `storage/memory.sqlite`
into categorized JSONL files suitable for RAG.

Why this exists:
- You don't want "fake" seed data.
- You want an automated, repeatable pipeline that produces stable KB entries
  with provenance fields.

Notes:
- This script DOES NOT fetch the web. Put your sources into a local folder first.
- Requires `OPENAI_API_KEY` (and optional `OPENAI_BASE_URL`).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable

from dotenv import load_dotenv
from openai import OpenAI
from openai import APIConnectionError, APIError, RateLimitError


DEFAULT_CATEGORIES = ["visa", "playbook", "transport", "packing", "safety", "misc"]


@dataclass(frozen=True)
class Source:
    kind: str  # "file" | "memory"
    ref: str   # filepath or session_id
    text: str


def _today() -> str:
    return os.getenv("DISTILL_DATE", str(date.today()))


def _sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def _make_id(category: str, title: str, source_ref: str) -> str:
    h = _sha1(f"{category}|{title}|{source_ref}")[:12]
    return f"{category}:{h}"


def _read_text_file(path: Path) -> str:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    # Very light cleanup; we want the LLM to see the real text.
    raw = raw.replace("\r\n", "\n")
    return raw.strip()


def _strip_html(html: str) -> str:
    # Minimal HTML stripping without adding dependencies.
    html = re.sub(r"(?is)<(script|style).*?>.*?</\\1>", " ", html)
    html = re.sub(r"(?is)<br\\s*/?>", "\n", html)
    html = re.sub(r"(?is)</p\\s*>", "\n\n", html)
    html = re.sub(r"(?is)<.*?>", " ", html)
    html = re.sub(r"[ \t]+", " ", html)
    html = re.sub(r"\n{3,}", "\n\n", html)
    return html.strip()


def _load_sources_from_dir(input_dir: Path) -> list[Source]:
    if not input_dir.exists():
        raise FileNotFoundError(f"Input dir not found: {input_dir}")

    sources: list[Source] = []
    for path in sorted(input_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".txt", ".md", ".markdown", ".html", ".htm"}:
            continue
        text = _read_text_file(path)
        if not text:
            continue
        if path.suffix.lower() in {".html", ".htm"}:
            text = _strip_html(text)
        sources.append(Source(kind="file", ref=str(path), text=text))
    return sources


def _load_sources_from_memory(db_path: Path, limit_sessions: int | None = None) -> list[Source]:
    if not db_path.exists():
        raise FileNotFoundError(f"DB not found: {db_path}")

    with sqlite3.connect(str(db_path)) as conn:
        session_rows = conn.execute(
            "SELECT DISTINCT session_id FROM messages ORDER BY session_id ASC"
        ).fetchall()
        session_ids = [str(r[0]) for r in session_rows]
        if limit_sessions is not None:
            session_ids = session_ids[: max(0, int(limit_sessions))]

        sources: list[Source] = []
        for sid in session_ids:
            rows = conn.execute(
                "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id ASC",
                (sid,),
            ).fetchall()
            lines: list[str] = []
            for role, content in rows:
                r = str(role)
                c = str(content or "").strip()
                if not c:
                    continue
                if r == "user":
                    lines.append(f"用户：{c}")
                elif r == "assistant":
                    lines.append(f"助手：{c}")
                else:
                    lines.append(f"{r}：{c}")
            joined = "\n".join(lines).strip()
            if joined:
                sources.append(Source(kind="memory", ref=sid, text=joined))
    return sources


def _chunk_text(text: str, max_chars: int, overlap: int) -> list[str]:
    t = (text or "").strip()
    if not t:
        return []
    if max_chars <= 200:
        return [t]
    if overlap < 0:
        overlap = 0
    overlap = min(overlap, max_chars // 3)

    chunks: list[str] = []
    start = 0
    n = len(t)
    while start < n:
        end = min(n, start + max_chars)
        chunk = t[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= n:
            break
        start = max(0, end - overlap)
    return chunks


SYSTEM_PROMPT = (
    "你是旅游知识库蒸馏器。你把输入资料蒸馏成可用于 RAG 的知识条目。\n"
    "要求：\n"
    "1) 只输出 JSON（不要 Markdown），输出一个 JSON 数组。\n"
    "2) 数组里每个元素是一个对象，必须包含字段：category,title,content,tags。\n"
    "3) category 只能是：visa,playbook,transport,packing,safety,misc。\n"
    "4) content 要可执行、分段清晰，包含清单/常见坑/例子/行动建议（能写就写）。\n"
    "5) 不要编造官方政策细节；遇到不确定或时效性强的信息，用“以官方最新为准”的表述。\n"
    "6) 去重：同一段资料不要重复输出非常相似的条目。\n"
)


USER_PROMPT_TEMPLATE = (
    "请从下面资料中蒸馏出 1-3 条知识条目（宁少勿滥）。\n"
    "每条 content 建议结构：核心要点/清单/常见坑/例子/行动建议。\n"
    "tags 用 5-12 个中文短词。\n\n"
    "[资料]\n"
    "{text}\n"
)


def _extract_json_array(s: str) -> list[dict[str, Any]]:
    raw = (s or "").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        return []
    except Exception:
        pass

    # Recovery: find first '[' and last ']' and try again.
    i = raw.find("[")
    j = raw.rfind("]")
    if 0 <= i < j:
        snippet = raw[i : j + 1]
        try:
            data = json.loads(snippet)
            if isinstance(data, list):
                return [x for x in data if isinstance(x, dict)]
        except Exception:
            return []
    return []


def _normalize_item(item: dict[str, Any], source: Source) -> dict[str, Any] | None:
    category = str(item.get("category") or "").strip()
    title = str(item.get("title") or "").strip()
    content = str(item.get("content") or "").strip()
    tags = item.get("tags")
    if category not in set(DEFAULT_CATEGORIES):
        category = "misc"
    if not title or not content:
        return None
    if not isinstance(tags, list):
        tags = []
    tags = [str(t).strip() for t in tags if str(t).strip()]
    tags = tags[:12]

    enriched: dict[str, Any] = {
        "id": _make_id(category, title, source.ref),
        "category": category,
        "title": title,
        "content": content,
        "tags": tags,
        "source_kind": source.kind,
        "source_ref": source.ref,
        "updated_at": _today(),
        "lang": "zh-CN",
    }
    # Optional metadata if present
    for k in ["city", "country"]:
        v = item.get(k)
        if v:
            enriched[k] = str(v).strip()
    return enriched


def _client_from_env() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "Missing OPENAI_API_KEY (tip: put it in .env and rerun; this script calls load_dotenv())"
        )
    base_url = os.getenv("OPENAI_BASE_URL", "").strip()
    return OpenAI(api_key=api_key, base_url=base_url) if base_url else OpenAI(api_key=api_key)


def _call_distill(
    client: OpenAI,
    model: str,
    text: str,
    max_output_tokens: int,
    temperature: float,
) -> list[dict[str, Any]]:
    prompt = USER_PROMPT_TEMPLATE.format(text=text)
    last_err: Exception | None = None
    for attempt in range(1, 6):
        try:
            resp = client.responses.create(
                model=model,
                input=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                max_output_tokens=max_output_tokens,
                temperature=temperature,
            )
            return _extract_json_array(resp.output_text or "")
        except (RateLimitError, APIConnectionError, APIError) as exc:
            last_err = exc
            # Simple backoff; keep it predictable.
            time.sleep(min(8.0, 0.8 * attempt))
            continue
    if last_err:
        raise last_err
    return []


def _write_jsonl(path: Path, items: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("a", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False))
            f.write("\n")
            n += 1
    return n


def _reset_outputs(out_dir: Path, categories: list[str]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for c in categories:
        p = out_dir / f"{c}.jsonl"
        if p.exists():
            p.unlink()


def distill_sources(
    sources: list[Source],
    out_dir: Path,
    model: str,
    max_output_tokens: int,
    temperature: float,
    chunk_chars: int,
    chunk_overlap: int,
    sleep_s: float,
    limit_items: int | None,
    dry_run: bool,
) -> dict[str, int]:
    client = _client_from_env()
    categories = list(DEFAULT_CATEGORIES)
    counts = {c: 0 for c in categories}

    if not dry_run:
        _reset_outputs(out_dir, categories)

    written_total = 0
    for src in sources:
        for chunk in _chunk_text(src.text, max_chars=chunk_chars, overlap=chunk_overlap):
            raw_items = _call_distill(
                client=client,
                model=model,
                text=chunk,
                max_output_tokens=max_output_tokens,
                temperature=temperature,
            )
            normalized: list[dict[str, Any]] = []
            for it in raw_items:
                norm = _normalize_item(it, src)
                if norm:
                    normalized.append(norm)

            if not normalized:
                if sleep_s:
                    time.sleep(sleep_s)
                continue

            if dry_run:
                for it in normalized:
                    counts[it["category"]] += 1
                    written_total += 1
                if limit_items is not None and written_total >= limit_items:
                    return counts
                if sleep_s:
                    time.sleep(sleep_s)
                continue

            by_cat: dict[str, list[dict[str, Any]]] = {}
            for it in normalized:
                by_cat.setdefault(it["category"], []).append(it)

            for cat, items in by_cat.items():
                if not items:
                    continue
                written = _write_jsonl(out_dir / f"{cat}.jsonl", items)
                counts[cat] += written
                written_total += written

            if limit_items is not None and written_total >= limit_items:
                return counts
            if sleep_s:
                time.sleep(sleep_s)
    return counts


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--out", default="knowledge_distilled", help="Output dir for jsonl files")
    common.add_argument("--model", default=os.getenv("OPENAI_MODEL", "gpt-5.2"), help="Distillation model")
    common.add_argument("--max-output-tokens", type=int, default=900, help="Max output tokens per chunk")
    common.add_argument("--temperature", type=float, default=0.2, help="Lower is more stable")
    common.add_argument("--chunk-chars", type=int, default=4500, help="Chunk size by characters")
    common.add_argument("--chunk-overlap", type=int, default=400, help="Chunk overlap by characters")
    common.add_argument("--sleep", type=float, default=0.2, help="Sleep seconds between calls")
    common.add_argument("--limit-items", type=int, default=None, help="Stop after N items written")
    common.add_argument("--dry-run", action="store_true", help="Do not write files, only count")

    ap_docs = sub.add_parser("docs", parents=[common], help="Distill from local documents directory")
    ap_docs.add_argument("--in", dest="input_dir", default="raw_docs", help="Input dir of .txt/.md/.html files")

    ap_mem = sub.add_parser("memory", parents=[common], help="Distill from storage/memory.sqlite")
    ap_mem.add_argument("--db", default="storage/memory.sqlite", help="SQLite path for conversation memory")
    ap_mem.add_argument("--limit-sessions", type=int, default=None, help="Only use the first N sessions")

    return ap


def main() -> int:
    load_dotenv()
    ap = build_parser()
    args = ap.parse_args()

    out_dir = Path(str(args.out))
    if args.cmd == "docs":
        sources = _load_sources_from_dir(Path(str(args.input_dir)))
    else:
        sources = _load_sources_from_memory(Path(str(args.db)), limit_sessions=args.limit_sessions)

    if not sources:
        print("No sources found.", file=sys.stderr)
        return 2

    counts = distill_sources(
        sources=sources,
        out_dir=out_dir,
        model=str(args.model),
        max_output_tokens=int(args.max_output_tokens),
        temperature=float(args.temperature),
        chunk_chars=int(args.chunk_chars),
        chunk_overlap=int(args.chunk_overlap),
        sleep_s=float(args.sleep),
        limit_items=args.limit_items,
        dry_run=bool(args.dry_run),
    )

    print("Done. Items by category:")
    for c in DEFAULT_CATEGORIES:
        print(f"- {c}: {counts.get(c, 0)}")
    if args.dry_run:
        print("(dry-run; no files written)")
    else:
        print(f"Output: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
