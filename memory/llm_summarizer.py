import logging
from typing import Optional

from openai import OpenAI


class LLMSummarizer:
    def __init__(
        self,
        api_key: Optional[str],
        base_url: Optional[str],
        model: str,
        max_output_tokens: int,
        enabled: bool = True,
    ) -> None:
        self.enabled = enabled
        self.model = model
        self.max_output_tokens = max_output_tokens
        self.logger = logging.getLogger(__name__)
        self.client = OpenAI(api_key=api_key, base_url=base_url) if base_url else OpenAI(api_key=api_key)

    def __call__(self, old_summary: str, old_items: list[tuple[int, str, str]], max_chars: int) -> str:
        if not self.enabled or not old_items:
            return ""

        lines: list[str] = []
        for _, role, content in old_items:
            label = "用户" if role == "user" else "助手"
            lines.append(f"- {label}: {self._normalize_text(content)}")
        history_text = "\n".join(lines)

        user_prompt = (
            "请把“已有摘要”和“新增历史对话”融合为一份更短、更稳态的记忆摘要。\n"
            "要求：\n"
            "1) 只保留长期有用信息：用户偏好、约束、既定决策、未完成事项。\n"
            "2) 删除寒暄、重复、一次性细节。\n"
            "3) 若新信息与旧信息冲突，以新信息为准。\n"
            f"4) 输出长度不超过 {max_chars} 个字符，中文。\n\n"
            f"[已有摘要]\n{old_summary or '（无）'}\n\n"
            f"[新增历史对话]\n{history_text}"
        )
        try:
            response = self.client.responses.create(
                model=self.model,
                input=[
                    {
                        "role": "system",
                        "content": "你是对话记忆压缩器，只输出摘要正文，不要解释。",
                    },
                    {"role": "user", "content": user_prompt},
                ],
                max_output_tokens=self.max_output_tokens,
            )
            text = (response.output_text or "").strip()
            if not text:
                return ""
            return text[:max_chars].strip()
        except Exception as exc:  # pragma: no cover - summarize should not break chat
            self.logger.warning("LLM summary failed, fallback to rule summary: %s", exc)
            return ""

    @staticmethod
    def _normalize_text(text: str, limit: int = 320) -> str:
        cleaned = " ".join((text or "").split())
        if len(cleaned) <= limit:
            return cleaned
        return cleaned[: limit - 1].rstrip() + "…"
