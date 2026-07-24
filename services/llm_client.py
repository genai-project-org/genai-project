"""Drop-in replacement for the `emergentintegrations.llm.*` API surface.

Talks to Anthropic and OpenAI directly via their native SDKs instead of routing
through the Emergent proxy. Routing is by the `provider` string passed to
`LlmChat.with_model(provider, model)`:

    "anthropic" -> ANTHROPIC_API_KEY
    "openai"    -> OPENAI_API_KEY

The `api_key=` argument that call sites still pass (the old, now-empty
`EMERGENT_LLM_KEY`) is accepted and ignored — real keys come from the per-provider
env vars above.
"""
import os
import base64
from dataclasses import dataclass
from typing import AsyncGenerator, List, Optional

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
MAX_TOKENS = int(os.environ.get("LLM_MAX_TOKENS", "4096"))


def _require_key(provider: str) -> str:
    key = ANTHROPIC_API_KEY if provider == "anthropic" else OPENAI_API_KEY
    if not key:
        env = "ANTHROPIC_API_KEY" if provider == "anthropic" else "OPENAI_API_KEY"
        raise RuntimeError(f"{env} is not set — add it to backend/.env and restart.")
    return key


# ---- emergent-compatible message types -----------------------------------

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
    """Terminal streaming event (marker only, matches emergent's sentinel)."""


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

    def with_model(self, provider: str, model: str) -> "LlmChat":
        self.provider = provider
        self.model = model
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
        if self.provider == "anthropic":
            client = AsyncAnthropic(api_key=_require_key("anthropic"))
            resp = await client.messages.create(
                model=self.model,
                max_tokens=MAX_TOKENS,
                system=self.system or None,
                messages=[{"role": "user", "content": self._anthropic_content(msg)}],
            )
            return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        client = AsyncOpenAI(api_key=_require_key("openai"))
        resp = await client.chat.completions.create(
            model=self.model,
            messages=self._openai_messages(msg),
            # ponytail: gpt-5/reasoning models require max_completion_tokens (not max_tokens);
            # bump LLM_MAX_TOKENS if long answers get truncated.
            max_completion_tokens=MAX_TOKENS,
        )
        return resp.choices[0].message.content or ""

    # -- streaming --

    async def stream_message(self, msg: UserMessage) -> AsyncGenerator[object, None]:
        if self.provider == "anthropic":
            client = AsyncAnthropic(api_key=_require_key("anthropic"))
            async with client.messages.stream(
                model=self.model,
                max_tokens=MAX_TOKENS,
                system=self.system or None,
                messages=[{"role": "user", "content": self._anthropic_content(msg)}],
            ) as stream:
                async for text in stream.text_stream:
                    if text:
                        yield TextDelta(content=text)
            yield StreamDone()
            return
        client = AsyncOpenAI(api_key=_require_key("openai"))
        stream = await client.chat.completions.create(
            model=self.model,
            messages=self._openai_messages(msg),
            max_completion_tokens=MAX_TOKENS,
            stream=True,
        )
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta.content
            if delta:
                yield TextDelta(content=delta)
        yield StreamDone()


# ---- image generation ------------------------------------------------------

class OpenAIImageGeneration:
    def __init__(self, api_key: Optional[str] = None):
        self._client = AsyncOpenAI(api_key=OPENAI_API_KEY)

    async def generate_images(self, prompt: str, model: str = "gpt-image-1",
                              number_of_images: int = 1, quality: str = "low") -> List[bytes]:
        resp = await self._client.images.generate(
            model=model,
            prompt=prompt,
            n=number_of_images,
            quality=quality,
            # ponytail: gpt-image-1 defaults to moderation="auto" which over-blocks
            # benign prompts; "low" is the least-restrictive supported setting.
            moderation="low",
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

    print("llm_client self-check OK")


if __name__ == "__main__":
    demo()
