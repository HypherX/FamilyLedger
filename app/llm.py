"""只发送模型名和消息。温度、长度等全部沿用接口默认值。"""
import json
import logging
from dataclasses import dataclass

from openai import OpenAI

logger = logging.getLogger("familyledger")
_CLIENTS: dict[tuple[str, str], OpenAI] = {}


@dataclass
class LLMSettings:
    base_url: str = ""
    api_key: str = ""
    model: str = ""

    def ready(self) -> bool:
        return bool(self.base_url.strip() and self.api_key.strip() and self.model.strip())


def get_client(settings: LLMSettings, timeout: float = 300) -> OpenAI:
    base = settings.base_url.strip().rstrip("/")
    key = (base, settings.api_key, timeout)
    client = _CLIENTS.get(key)
    if client is None:
        # timeout 只限制本机等待，不会作为模型参数发出去。
        client = OpenAI(base_url=base, api_key=settings.api_key, timeout=timeout)
        _CLIENTS[key] = client
    return client


def complete(settings: LLMSettings, messages: list[dict], timeout: float = 300) -> str:
    response = get_client(settings, timeout).chat.completions.create(
        model=settings.model.strip(),
        messages=messages,
    )
    message = response.choices[0].message
    content = message.content or ""
    if isinstance(content, list):
        parts = []
        for part in content:
            parts.append(part if isinstance(part, str) else str(getattr(part, "text", "") or ""))
        content = "".join(parts)
    if not str(content).strip():
        content = getattr(message, "reasoning_content", "") or ""
    return str(content)


def extract_json(text: str):
    start_obj = text.find("{")
    start_arr = text.find("[")
    if start_obj < 0 and start_arr < 0:
        raise ValueError("模型没有返回 JSON")
    if start_obj < 0 or (start_arr >= 0 and start_arr < start_obj):
        start = start_arr
    else:
        start = start_obj
    try:
        return json.JSONDecoder().raw_decode(text[start:])[0]
    except json.JSONDecodeError as exc:
        raise ValueError("模型返回的 JSON 无法解析") from exc


def chat_json(settings: LLMSettings, messages: list[dict], timeout: float = 180):
    text = complete(settings, messages, timeout=timeout)
    try:
        return extract_json(text)
    except ValueError:
        logger.info("模型返回无法直接解析，重试一次")
        retry = messages + [
            {"role": "assistant", "content": text[:4000]},
            {"role": "user", "content": "请只输出一个 JSON 对象，不要使用 Markdown，不要解释。"},
        ]
        return extract_json(complete(settings, retry, timeout=timeout))
