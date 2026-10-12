"""LLM client — talks to Anthropic and OpenAI directly via their native SDKs.

Routing is by the `provider` string passed to `LlmChat.with_model(provider, model)`:

    "anthropic" -> ANTHROPIC_API_KEY
    "openai"    -> OPENAI_API_KEY
    "google"    -> GEMINI_API_KEY (via its OpenAI-compatible endpoint)

`LlmChat`'s `api_key=` constructor argument is accepted for backward
compatibility with older call sites but ignored — real keys always come from
the per-provider env vars above.
"""
import json
import logging
import os
import base64
from dataclasses import dataclass
from types import SimpleNamespace
from typing import AsyncGenerator, List, Optional

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
MAX_TOKENS = int(os.environ.get("LLM_MAX_TOKENS", "4096"))
# Ceiling for non-streaming calls; above this the SDKs demand streaming.
NONSTREAM_MAX_TOKENS = int(os.environ.get("LLM_NONSTREAM_MAX_TOKENS", "16000"))
# Gemini speaks the OpenAI chat-completions dialect here, so provider "google"
# reuses the AsyncOpenAI path instead of pulling in a third request builder.
GEMINI_BASE_URL = os.environ.get(
    "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/"
)
# Tool-use fallback target (see LlmChat.create_with_tools) — "gpt-5" rather
# than the cheaper gpt-5-mini default elsewhere in this codebase, since this
# only ever substitutes for claude-sonnet-5 running something as substantial
# as a live mock interview, not a cheap/quick task.
OPENAI_FALLBACK_MODEL = os.environ.get("OPENAI_FALLBACK_MODEL", "gpt-5")

_KEY_ENV = {
    "anthropic": ("ANTHROPIC_API_KEY", ANTHROPIC_API_KEY),
    "openai": ("OPENAI_API_KEY", OPENAI_API_KEY),
    "google": ("GEMINI_API_KEY", GEMINI_API_KEY),
}


def _require_key(provider: str) -> str:
    env, key = _KEY_ENV.get(provider, _KEY_ENV["openai"])
    if not key:
        raise RuntimeError(f"{env} is not set — add it to backend/.env and restart.")
    return key


def _openai_client(provider: str) -> AsyncOpenAI:
    """AsyncOpenAI pointed at OpenAI or at Gemini's OpenAI-compatible endpoint."""
    if provider == "google":
        return AsyncOpenAI(api_key=_require_key("google"), base_url=GEMINI_BASE_URL)
    return AsyncOpenAI(api_key=_require_key("openai"))


# ---- chat message types ---------------------------------------------------

@dataclass
class ImageContent:
    image_base64: str


@dataclass
class UserMessage:
    text: str
    file_contents: Optional[List[ImageContent]] = None


@dataclass
class TextDelta:
    content: str


class StreamDone:
    """Terminal streaming event marker."""


# ---- helpers --------------------------------------------------------------

def _sniff_media_type(b64: str) -> str:
    """Guess an image media type from the first few decoded bytes.

    Defaults to image/png. Covers the formats a browser upload realistically sends.
    """
    try:
        head = base64.b64decode(b64[:24], validate=False)
    except Exception:
        return "image/png"
    if head[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":  # (head is short; best-effort)
        return "image/webp"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return "image/png"


# ---- chat client ----------------------------------------------------------

class LlmChat:
    def __init__(self, api_key: Optional[str] = None, session_id: Optional[str] = None,
                 system_message: str = ""):
        self.system = system_message or ""
        self.session_id = session_id  # kept for signature parity; not used by SDKs
        self.provider = "anthropic"
        self.model = "claude-haiku-4-5-20251001"
        self.max_tokens = MAX_TOKENS

    def with_model(self, provider: str, model: str,
                   max_tokens: Optional[int] = None) -> "LlmChat":
        self.provider = provider
        self.model = model
        # Thinking-by-default models need more headroom than LLM_MAX_TOKENS.
        self.max_tokens = max_tokens or MAX_TOKENS
        return self

    # -- request builders --

    def _anthropic_content(self, msg: UserMessage) -> list:
        content: list = [{"type": "text", "text": msg.text}]
        for img in (msg.file_contents or []):
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": _sniff_media_type(img.image_base64),
                    "data": img.image_base64,
                },
            })
        return content

    def _openai_messages(self, msg: UserMessage) -> list:
        user_content: list = [{"type": "text", "text": msg.text}]
        for img in (msg.file_contents or []):
            mt = _sniff_media_type(img.image_base64)
            user_content.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mt};base64,{img.image_base64}"},
            })
        messages = []
        if self.system:
            messages.append({"role": "system", "content": self.system})
        messages.append({"role": "user", "content": user_content})
        return messages

    # -- non-streaming --

    async def send_message(self, msg: UserMessage) -> str:
        # The SDKs refuse a non-streaming request whose max_tokens implies a >10min
        # run, so clamp here. Only stream_message() gets the full per-model budget.
        budget = min(self.max_tokens, NONSTREAM_MAX_TOKENS)
        if self.provider == "anthropic":
            try:
                return await self._send_message_anthropic(msg, budget)
            except Exception as e:
                # Same reasoning as create_with_tools: a one-shot call has no
                # in-flight state to translate, so the fallback here is just
                # "ask the other provider the same question" — no shape
                # normalization needed. Without this, every Anthropic-only
                # call site (e.g. interview_report_service's narrative pass)
                # silently degrades to "No verdict generated" / empty
                # strengths any time Anthropic is unavailable, which reads as
                # a product bug, not a billing issue.
                logger.warning(f"LlmChat.send_message: Anthropic call failed ({e!r}); falling back to OpenAI")
                return await self._send_message_openai(msg, budget, model=OPENAI_FALLBACK_MODEL, provider="openai")
        return await self._send_message_openai(msg, budget, model=self.model, provider=self.provider)

    async def _send_message_anthropic(self, msg: UserMessage, budget: int) -> str:
        client = AsyncAnthropic(api_key=_require_key("anthropic"))
        resp = await client.messages.create(
            model=self.model,
            max_tokens=budget,
            system=self.system or None,
            messages=[{"role": "user", "content": self._anthropic_content(msg)}],
        )
        return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")

    async def _send_message_openai(self, msg: UserMessage, budget: int, model: str, provider: str) -> str:
        client = _openai_client(provider)
        resp = await client.chat.completions.create(
            model=model,
            messages=self._openai_messages(msg),
            # ponytail: gpt-5/reasoning models require max_completion_tokens (not max_tokens);
            # bump LLM_MAX_TOKENS if long answers get truncated.
            max_completion_tokens=budget,
        )
        return resp.choices[0].message.content or ""

    # -- streaming --

    async def stream_message(self, msg: UserMessage) -> AsyncGenerator[object, None]:
        if self.provider == "anthropic":
            client = AsyncAnthropic(api_key=_require_key("anthropic"))
            async with client.messages.stream(
                model=self.model,
                max_tokens=self.max_tokens,
                system=self.system or None,
                messages=[{"role": "user", "content": self._anthropic_content(msg)}],
            ) as stream:
                async for text in stream.text_stream:
                    if text:
                        yield TextDelta(content=text)
            yield StreamDone()
            return
        client = _openai_client(self.provider)
        stream = await client.chat.completions.create(
            model=self.model,
            messages=self._openai_messages(msg),
            max_completion_tokens=self.max_tokens,
            stream=True,
        )
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta.content
            if delta:
                yield TextDelta(content=delta)
        yield StreamDone()

    # -- tool-use (Anthropic primary, OpenAI fallback) --

    async def create_with_tools(self, messages: list, tools: list,
                                 system: Optional[str] = None, max_tokens: Optional[int] = None):
        """One tool-use call. Returns an object shaped like Anthropic's
        `Message` regardless of which provider actually served it: `.content`
        is a list of blocks with `.type` in ("text", "tool_use") — text
        blocks have `.text`, tool_use blocks have `.id`/`.name`/`.input` — and
        `.stop_reason` is "tool_use" or "end_turn". Callers (see
        interview_agent.run_turn) inspect this shape and manage the message
        history themselves; this method makes exactly one call and does not
        loop.

        `messages` is ALWAYS in this same Anthropic-block shape too (never
        OpenAI's), including whatever a PRIOR call in this same loop
        returned — _create_with_tools_openai() translates it to/from OpenAI's
        wire format internally, on every call, so the caller's message list
        never needs to know which provider actually served any given turn.

        Fallback: if the primary `self.provider == "anthropic"` call raises
        (most often a billing/availability failure — out of credits, rate
        limited, an outage), this retries the SAME call against OpenAI
        (OPENAI_FALLBACK_MODEL) before giving up. This is why the
        shape-normalization above exists at all — Mock Interview's agent loop
        (services/interview_agent.py) can keep speaking one format without
        caring which provider is actually behind any given turn, including
        turns from BEFORE a mid-session failover.
        """
        if self.provider == "anthropic":
            try:
                return await self._create_with_tools_anthropic(messages, tools, system, max_tokens)
            except Exception as e:
                logger.warning(f"LlmChat.create_with_tools: Anthropic call failed ({e!r}); falling back to OpenAI")
                try:
                    return await self._create_with_tools_openai(
                        messages, tools, system, max_tokens, model=OPENAI_FALLBACK_MODEL,
                    )
                except Exception:
                    logger.exception("LlmChat.create_with_tools: OpenAI fallback also failed")
                    raise e  # surface the ORIGINAL Anthropic failure — more actionable than the fallback's own error
        if self.provider == "openai":
            return await self._create_with_tools_openai(messages, tools, system, max_tokens, model=self.model)
        raise NotImplementedError(
            f"Tool-use isn't supported for provider {self.provider!r} — only anthropic (with an openai fallback) and openai."
        )

    async def _create_with_tools_anthropic(self, messages: list, tools: list,
                                           system: Optional[str], max_tokens: Optional[int]):
        client = AsyncAnthropic(api_key=_require_key("anthropic"))
        return await client.messages.create(
            model=self.model,
            max_tokens=max_tokens or self.max_tokens,
            system=system if system is not None else (self.system or None),
            messages=self._sanitize_for_anthropic(messages),
            tools=tools,
        )

    @staticmethod
    def _sanitize_for_anthropic(messages: list) -> list:
        """Converts any content block that isn't already a plain dict (a real
        Anthropic SDK object from an EARLIER iteration of THIS SAME tool loop
        that actually ran on Anthropic, or a SimpleNamespace pseudo-block from
        an earlier iteration that fell back to OpenAI — see
        _openai_response_to_anthropic_shape) into a plain JSON-serializable
        dict. Without this, once a tool loop falls back to OpenAI even once,
        every subsequent iteration's Anthropic retry crashes with "Object of
        type SimpleNamespace is not JSON serializable" the moment httpx tries
        to encode the request body — Anthropic's own SDK objects happen to be
        safe to serialize directly, which is why this bug only ever surfaces
        after at least one fallback has already happened in the same loop."""
        def get(block, key, default=None):
            return getattr(block, key, None) if not isinstance(block, dict) else block.get(key, default)

        out = []
        for m in messages:
            content = m["content"]
            if isinstance(content, str):
                out.append(m)
                continue
            new_blocks = []
            for b in content:
                if isinstance(b, dict):
                    new_blocks.append(b)
                elif get(b, "type") == "text":
                    new_blocks.append({"type": "text", "text": get(b, "text")})
                elif get(b, "type") == "tool_use":
                    new_blocks.append({"type": "tool_use", "id": get(b, "id"), "name": get(b, "name"), "input": get(b, "input") or {}})
                else:
                    new_blocks.append(b)  # unrecognized shape — pass through best-effort
            out.append({"role": m["role"], "content": new_blocks})
        return out

    async def _create_with_tools_openai(self, messages: list, tools: list,
                                        system: Optional[str], max_tokens: Optional[int], model: str):
        client = _openai_client("openai")
        openai_messages = self._anthropic_messages_to_openai(
            messages, system if system is not None else (self.system or None),
        )
        openai_tools = [
            {"type": "function", "function": {
                "name": t["name"], "description": t.get("description", ""),
                "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
            }}
            for t in tools
        ]
        resp = await client.chat.completions.create(
            model=model,
            messages=openai_messages,
            tools=openai_tools,
            max_completion_tokens=max_tokens or self.max_tokens,
        )
        return self._openai_response_to_anthropic_shape(resp)

    @staticmethod
    def _anthropic_messages_to_openai(messages: list, system: Optional[str]) -> list:
        """Translates an Anthropic-block-shaped message history (see
        create_with_tools's docstring) into OpenAI's chat-completions shape.
        Every block is accessed via getattr/.get duck-typing since a block
        may be a real Anthropic SDK object (this provider's own prior turn),
        a SimpleNamespace from _openai_response_to_anthropic_shape (a PRIOR
        turn that was itself served by the OpenAI fallback), or a plain dict
        (the tool_result entries interview_agent.run_turn builds by hand)."""
        def get(block, key, default=None):
            return getattr(block, key, None) if not isinstance(block, dict) else block.get(key, default)

        out = []
        if system:
            out.append({"role": "system", "content": system})
        for m in messages:
            content = m["content"]
            if isinstance(content, str):
                out.append({"role": m["role"], "content": content})
                continue
            if m["role"] == "user" and content and get(content[0], "type") == "tool_result":
                # Anthropic nests every tool result for a turn under one user
                # message; OpenAI wants each as its own standalone "tool" message.
                for block in content:
                    out.append({
                        "role": "tool",
                        "tool_call_id": get(block, "tool_use_id"),
                        "content": get(block, "content", ""),
                    })
                continue
            # Assistant turn: a mix of text block(s) and/or tool_use block(s).
            text_parts = [get(b, "text") for b in content if get(b, "type") == "text"]
            tool_use_blocks = [b for b in content if get(b, "type") == "tool_use"]
            assistant_msg = {"role": "assistant", "content": "".join(p for p in text_parts if p) or None}
            if tool_use_blocks:
                assistant_msg["tool_calls"] = [
                    {
                        "id": get(b, "id"), "type": "function",
                        "function": {"name": get(b, "name"), "arguments": json.dumps(get(b, "input") or {})},
                    }
                    for b in tool_use_blocks
                ]
            out.append(assistant_msg)
        return out

    @staticmethod
    def _openai_response_to_anthropic_shape(resp):
        msg = resp.choices[0].message
        blocks = []
        if msg.content:
            blocks.append(SimpleNamespace(type="text", text=msg.content))
        for tc in (msg.tool_calls or []):
            try:
                args = json.loads(tc.function.arguments or "{}")
            except Exception:
                args = {}
            blocks.append(SimpleNamespace(type="tool_use", id=tc.id, name=tc.function.name, input=args))
        stop_reason = "tool_use" if msg.tool_calls else "end_turn"
        return SimpleNamespace(content=blocks, stop_reason=stop_reason)


# ---- image generation ------------------------------------------------------

class OpenAIImageGeneration:
    def __init__(self, api_key: Optional[str] = None, provider: str = "openai"):
        # Gemini's OpenAI-compatible endpoint serves images.generate too, so the
        # same client class covers both providers.
        self.provider = provider
        self._client = _openai_client(provider)

    async def generate_images(self, prompt: str, model: str = "gpt-image-1",
                              number_of_images: int = 1, quality: str = "low") -> List[bytes]:
        extra = {}
        if self.provider == "openai":
            # quality/moderation are OpenAI-only; Gemini's compat layer rejects them.
            # ponytail: gpt-image-1 defaults to moderation="auto" which over-blocks
            # benign prompts; "low" is the least-restrictive supported setting.
            extra = {"quality": quality, "moderation": "low"}
        resp = await self._client.images.generate(
            model=model,
            prompt=prompt,
            n=number_of_images,
            **extra,
        )
        return [base64.b64decode(d.b64_json) for d in resp.data]


# ---- offline self-check ----------------------------------------------------

def demo():
    """Runs without network: verifies request builders and image sniffing."""
    # 1x1 transparent PNG
    png_b64 = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nG"
               "NgYGAAAAAEAAH2FzhVAAAAAElFTkSuQmCC")
    assert _sniff_media_type(png_b64) == "image/png"
    assert _sniff_media_type("/9j/4AAQSkZJRg==") == "image/jpeg"  # jpeg magic

    chat = LlmChat(system_message="sys").with_model("anthropic", "claude-x")
    assert chat.provider == "anthropic" and chat.model == "claude-x"
    ac = chat._anthropic_content(UserMessage(text="hi", file_contents=[ImageContent(png_b64)]))
    assert ac[0] == {"type": "text", "text": "hi"}
    assert ac[1]["type"] == "image" and ac[1]["source"]["media_type"] == "image/png"

    chat_o = LlmChat(system_message="sys").with_model("openai", "gpt-5")
    om = chat_o._openai_messages(UserMessage(text="hi", file_contents=[ImageContent(png_b64)]))
    assert om[0] == {"role": "system", "content": "sys"}
    assert om[1]["role"] == "user"
    assert om[1]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")

    # gemini rides the openai request builder, so only provider/base_url differ
    chat_g = LlmChat(system_message="sys").with_model("google", "gemini-3.6-flash")
    assert chat_g.provider == "google"
    assert chat_g._openai_messages(UserMessage(text="hi"))[0]["role"] == "system"
    assert set(_KEY_ENV) == {"anthropic", "openai", "google"}

    # per-model output budget: explicit wins, omitted/None falls back to the env default
    assert chat.max_tokens == MAX_TOKENS
    assert LlmChat().with_model("anthropic", "claude-opus-5", 32000).max_tokens == 32000
    assert LlmChat().with_model("anthropic", "claude-x", None).max_tokens == MAX_TOKENS

    print("llm_client self-check OK")


if __name__ == "__main__":
    demo()
