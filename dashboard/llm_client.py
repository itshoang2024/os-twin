"""
Multi-provider LLM client abstraction.

Supports: OpenAI, Anthropic (via OpenAI-compatible API), Google (Gemini), and OpenAI-compatible endpoints.
Uses provider_urls.json for base URLs.
"""

from __future__ import annotations

import os
import asyncio
import base64
import json
import logging
import mimetypes
import threading
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Literal, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

PROVIDER_URLS_PATH = Path(__file__).parent.parent / "provider_urls.json"

Role = Literal["user", "assistant", "system", "tool"]

MAX_RETRIES = 3
RETRY_DELAY = 1.0
REQUEST_TIMEOUT = 120.0


def load_provider_urls() -> dict:
    if not PROVIDER_URLS_PATH.exists():
        logger.warning(f"provider_urls.json not found at {PROVIDER_URLS_PATH}")
        return {}
    with open(PROVIDER_URLS_PATH) as f:
        return json.load(f)


PROVIDER_URLS = load_provider_urls()


def _detect_mime_type(url: str) -> str:
    """Detect mime type from URL or data URI."""
    if url.startswith("data:"):
        mime_end = url.find(";")
        if mime_end > 5:
            return url[5:mime_end]
        return "image/jpeg"

    parsed = urlparse(url)
    path = parsed.path.lower()
    mime_type, _ = mimetypes.guess_type(path)
    return mime_type or "image/jpeg"


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict = field(default_factory=dict)
    thought_signature: Optional[str] = None

    def __repr__(self) -> str:
        return f"ToolCall(id={self.id!r}, name={self.name!r})"


@dataclass
class ChatMessage:
    role: Role
    content: Optional[str] = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: Optional[str] = None
    name: Optional[str] = None
    thought_signature: Optional[str] = None
    images: list[str] = field(default_factory=list)

    def __repr__(self) -> str:
        preview = self.content[:50] if self.content else None
        return f"ChatMessage(role={self.role!r}, content={preview}...)"


@dataclass
class LLMConfig:
    max_tokens: int = None
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    stop: Optional[list[str]] = None


class LLMError(Exception):
    def __init__(self, message: str, provider: Optional[str] = None, original_error: Optional[Exception] = None):
        super().__init__(message)
        self.provider = provider
        self.original_error = original_error


class LLMClient(ABC):
    def __init__(self, model: str, config: Optional[LLMConfig] = None, provider: Optional[str] = None):
        self.model = model
        self.config = config or LLMConfig()
        self.provider = provider

    @abstractmethod
    async def chat(
        self,
        messages: list[ChatMessage],
        tools: Optional[list[dict]] = None,
        tool_choice: Optional[str] = None,
        response_format: Optional[dict] = None,
    ) -> ChatMessage:
        pass

    @abstractmethod
    async def chat_stream(
        self,
        messages: list[ChatMessage],
        tools: Optional[list[dict]] = None,
        tool_choice: Optional[str] = None,
        response_format: Optional[dict] = None,
    ) -> AsyncIterator[str | ToolCall]:
        pass

    def _truncate_messages(self, messages: list[ChatMessage]) -> list[ChatMessage]:
        """Truncate message content to fit within the model's context window.

        Delegates all context-limit lookup and content trimming to
        :func:`models_dev_loader.truncate_messages_for_model`.  This method
        only handles ChatMessage ↔ dict conversion.
        """
        try:
            from dashboard.lib.settings.models_dev_loader import truncate_messages_for_model

            provider = self.provider or ""
            dicts = [{"role": m.role, "content": m.content or ""} for m in messages]
            truncated = truncate_messages_for_model(dicts, provider, self.model)

            result = []
            for orig, trunc in zip(messages, truncated):
                new_content = trunc.get("content", orig.content)
                if new_content != (orig.content or ""):
                    result.append(ChatMessage(
                        role=orig.role,
                        content=new_content,
                        tool_calls=orig.tool_calls,
                        tool_call_id=orig.tool_call_id,
                        name=orig.name,
                        thought_signature=orig.thought_signature,
                        images=orig.images,
                    ))
                else:
                    result.append(orig)
            return result
        except Exception as exc:
            logger.debug("Message truncation skipped: %s", exc)
            return messages

    async def _retry_with_backoff(self, coro, *args, **kwargs):
        last_error = None
        for attempt in range(MAX_RETRIES):
            try:
                return await coro(*args, **kwargs)
            except Exception as e:
                last_error = e
                if attempt < MAX_RETRIES - 1:
                    delay = RETRY_DELAY * (2**attempt)
                    logger.warning(
                        f"LLM request failed (attempt {attempt + 1}/{MAX_RETRIES}): {e}. Retrying in {delay}s..."
                    )
                    await asyncio.sleep(delay)
        raise LLMError(f"LLM request failed after {MAX_RETRIES} retries", original_error=last_error)


def _get_base_url(provider: str) -> Optional[str]:
    if provider in PROVIDER_URLS:
        return PROVIDER_URLS[provider].get("base")
    return None


class OpenAIClient(LLMClient):
    def __init__(
        self,
        model: str,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        config: Optional[LLMConfig] = None,
        provider: Optional[str] = None,
    ):
        super().__init__(model, config, provider=provider)
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=REQUEST_TIMEOUT)
        self.base_url = base_url

    def _convert_messages(self, messages: list[ChatMessage]) -> list[dict]:
        result = []
        for msg in messages:
            if msg.role == "tool":
                result.append(
                    {
                        "role": "tool",
                        "tool_call_id": msg.tool_call_id,
                        "content": msg.content or "",
                    }
                )
            elif msg.tool_calls:
                result.append(
                    {
                        "role": msg.role,
                        "content": msg.content,
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                            }
                            for tc in msg.tool_calls
                        ],
                    }
                )
            elif msg.images:
                content_parts = []
                if msg.content:
                    content_parts.append({"type": "text", "text": msg.content})
                for img_url in msg.images:
                    content_parts.append({"type": "image_url", "image_url": {"url": img_url}})
                result.append({"role": msg.role, "content": content_parts})
            else:
                result.append({"role": msg.role, "content": msg.content})
        return result

    def _convert_tools(self, tools: Optional[list[dict]]) -> Optional[list[dict]]:
        if not tools:
            return None
        return [{"type": "function", "function": t} for t in tools]

    async def chat(
        self,
        messages: list[ChatMessage],
        tools: Optional[list[dict]] = None,
        tool_choice: Optional[str] = None,
        response_format: Optional[dict] = None,
    ) -> ChatMessage:
        messages = self._truncate_messages(messages)

        async def _make_request():
            kwargs: dict = {
                "model": self.model,
                "messages": self._convert_messages(messages),
                "max_tokens": self.config.max_tokens,
            }
            if tools:
                kwargs["tools"] = self._convert_tools(tools)
            if tool_choice:
                kwargs["tool_choice"] = tool_choice
            if response_format:
                kwargs["response_format"] = response_format
            if self.config.temperature is not None:
                kwargs["temperature"] = self.config.temperature

            response = await self._client.chat.completions.create(**kwargs)
            choice = response.choices[0]

            tool_calls = []
            if choice.message.tool_calls:
                for tc in choice.message.tool_calls:
                    tool_calls.append(
                        ToolCall(
                            id=tc.id,
                            name=tc.function.name,
                            arguments=json.loads(tc.function.arguments),
                        )
                    )

            return ChatMessage(
                role=choice.message.role or "assistant",
                content=choice.message.content,
                tool_calls=tool_calls,
            )

        try:
            return await self._retry_with_backoff(_make_request)
        except LLMError:
            raise
        except Exception as e:
            raise LLMError(f"OpenAI API error: {e}", provider="openai", original_error=e)

    async def chat_stream(
        self,
        messages: list[ChatMessage],
        tools: Optional[list[dict]] = None,
        tool_choice: Optional[str] = None,
        response_format: Optional[dict] = None,
    ) -> AsyncIterator[str | ToolCall]:
        messages = self._truncate_messages(messages)
        kwargs: dict = {
            "model": self.model,
            "messages": self._convert_messages(messages),
            "max_tokens": self.config.max_tokens,
            "stream": True,
        }
        if tools:
            kwargs["tools"] = self._convert_tools(tools)
        if tool_choice:
            kwargs["tool_choice"] = tool_choice
        if response_format:
            kwargs["response_format"] = response_format
        if self.config.temperature is not None:
            kwargs["temperature"] = self.config.temperature

        tool_calls_accumulator: dict[str, dict] = {}

        try:
            stream = await self._client.chat.completions.create(**kwargs)
            async for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                if not delta:
                    continue

                if delta.content:
                    yield delta.content

                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        if tc.id and tc.id not in tool_calls_accumulator:
                            tool_calls_accumulator[tc.id] = {"id": tc.id, "name": "", "arguments": ""}

                        if tc.function:
                            key = tc.id or list(tool_calls_accumulator.keys())[-1] if tool_calls_accumulator else None
                            if key and key in tool_calls_accumulator:
                                if tc.function.name:
                                    tool_calls_accumulator[key]["name"] = tc.function.name
                                if tc.function.arguments:
                                    tool_calls_accumulator[key]["arguments"] += tc.function.arguments

            for tc_data in tool_calls_accumulator.values():
                try:
                    args = json.loads(tc_data["arguments"]) if tc_data["arguments"] else {}
                except json.JSONDecodeError:
                    args = {}
                yield ToolCall(id=tc_data["id"], name=tc_data["name"], arguments=args)
        except Exception as e:
            raise LLMError(f"OpenAI streaming error: {e}", provider="openai", original_error=e)



# Fields accepted by Gemini's Schema proto. Anything else (notably
# ``additionalProperties``, ``$schema``, ``strict``, ``definitions``,
# ``$ref``, ``oneOf``) must be stripped or the API returns 400.
_GEMINI_SCHEMA_ALLOWED_KEYS = frozenset({
    "type", "format", "description", "nullable", "enum", "title", "default",
    "example", "anyOf",
    "items", "minItems", "maxItems",
    "properties", "required", "propertyOrdering",
    "minProperties", "maxProperties",
    "pattern", "minLength", "maxLength",
    "minimum", "maximum",
})


def _sanitize_gemini_schema(node: Any) -> Any:
    """Recursively strip JSON-Schema fields Gemini's response_schema rejects.

    Filters dict keys by the Gemini allowlist, except inside ``properties``
    where the keys are user-defined field names that must be kept verbatim
    (only their schema values are sanitized).
    """
    if isinstance(node, dict):
        cleaned: dict = {}
        for k, v in node.items():
            if k not in _GEMINI_SCHEMA_ALLOWED_KEYS:
                continue
            if k == "properties" and isinstance(v, dict):
                cleaned[k] = {pk: _sanitize_gemini_schema(pv) for pk, pv in v.items()}
            elif k == "required" and isinstance(v, list):
                cleaned[k] = list(v)
            else:
                cleaned[k] = _sanitize_gemini_schema(v)
        return cleaned
    if isinstance(node, list):
        return [_sanitize_gemini_schema(v) for v in node]
    return node


class GoogleClient(LLMClient):
    # Gemini AI (consumer) OpenAI-compatible endpoint.
    # Vertex AI uses a separate region-scoped URL resolved by create_client.
    _GEMINI_OPENAI_BASE = "https://generativelanguage.googleapis.com/v1beta/openai/"

    def __init__(
        self,
        model: str,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        config: Optional[LLMConfig] = None,
        vertexai: bool = False,
        provider: Optional[str] = None,
    ):
        super().__init__(model, config, provider=provider)
        from google.genai import Client

        # Support model strings like "models/gemini-3.1-pro-preview" or plain "gemini-3.1-pro-preview".
        # The genai SDK expects only the bare model ID (last segment after "/").
        self.model_id = model.split("/")[-1]

        if vertexai:
            project = os.environ.get("GOOGLE_CLOUD_PROJECT")
            location = os.environ.get("VERTEX_LOCATION")
            self._client = Client(vertexai=True, project=project, location=location)
        else:
            self._client = Client(api_key=api_key)

        self.base_url = base_url or self._GEMINI_OPENAI_BASE

    def _convert_messages(self, messages: list[ChatMessage]) -> list:
        from google.genai import types

        result = []
        for msg in messages:
            if msg.role == "system":
                result.append(types.Content(role="user", parts=[types.Part(text=msg.content or "")]))
            elif msg.role == "tool":
                tool_name = msg.name or (msg.tool_call_id.replace("fc_", "") if msg.tool_call_id else "unknown_tool")
                func_response = types.Part.from_function_response(
                    name=tool_name, response={"result": msg.content or ""}
                )
                if msg.thought_signature:
                    func_response.thought_signature = msg.thought_signature
                result.append(types.Content(role="tool", parts=[func_response]))
            else:
                role = "user" if msg.role == "user" else "model"
                parts = []
                if msg.content:
                    parts.append(types.Part(text=msg.content))
                for img_url in msg.images:
                    mime_type = _detect_mime_type(img_url)
                    if img_url.startswith("data:"):
                        base64_data = img_url.split(",", 1)[-1] if "," in img_url else img_url
                        parts.append(types.Part.from_bytes(data=base64.b64decode(base64_data), mime_type=mime_type))
                    else:
                        parts.append(types.Part.from_uri(file_uri=img_url, mime_type=mime_type))
                if msg.tool_calls:
                    for tc in msg.tool_calls:
                        func_call_part = types.Part.from_function_call(name=tc.name, args=tc.arguments)
                        if tc.thought_signature:
                            func_call_part.thought_signature = tc.thought_signature
                        parts.append(func_call_part)
                if parts:
                    result.append(types.Content(role=role, parts=parts))
        return result

    def _convert_tools(self, tools: Optional[list[dict]]) -> Optional[list]:
        if not tools:
            return None
        from google.genai import types

        declarations = []
        for t in tools:
            declarations.append(
                types.FunctionDeclaration(
                    name=t["name"],
                    description=t.get("description", ""),
                    parameters=t.get("parameters", {}),
                )
            )
        return [types.Tool(function_declarations=declarations)]

    async def chat(
        self,
        messages: list[ChatMessage],
        tools: Optional[list[dict]] = None,
        tool_choice: Optional[str] = None,
        response_format: Optional[dict] = None,
    ) -> ChatMessage:
        messages = self._truncate_messages(messages)

        async def _make_request():
            from google.genai import types

            converted = self._convert_messages(messages)
            kwargs: dict = {"model": self.model_id, "contents": converted}
            converted_tools = self._convert_tools(tools)

            # Build GenerateContentConfig with tools and/or structured output
            config_kwargs: dict = {}
            if converted_tools:
                config_kwargs["tools"] = converted_tools
            if response_format:
                # Convert OpenAI-style response_format to Gemini's native format
                schema = response_format.get("json_schema", {}).get("schema", {})
                config_kwargs["response_mime_type"] = "application/json"
                if schema:
                    config_kwargs["response_schema"] = _sanitize_gemini_schema(schema)
            if config_kwargs:
                kwargs["config"] = types.GenerateContentConfig(**config_kwargs)

            response = await self._client.aio.models.generate_content(**kwargs)

            tool_calls = []
            text_content = None
            if response.candidates and response.candidates[0].content.parts:
                for part in response.candidates[0].content.parts:
                    if part.function_call:
                        tool_calls.append(
                            ToolCall(
                                id=f"fc_{uuid.uuid4().hex[:8]}",
                                name=part.function_call.name,
                                arguments=dict(part.function_call.args) if part.function_call.args else {},
                                thought_signature=getattr(part, "thought_signature", None),
                            )
                        )
                    elif part.text:
                        text_content = (text_content or "") + part.text

            return ChatMessage(role="assistant", content=text_content, tool_calls=tool_calls)

        try:
            return await self._retry_with_backoff(_make_request)
        except LLMError:
            raise
        except Exception as e:
            raise LLMError(f"Google API error: {e}", provider="google", original_error=e)

    async def chat_stream(
        self,
        messages: list[ChatMessage],
        tools: Optional[list[dict]] = None,
        tool_choice: Optional[str] = None,
        response_format: Optional[dict] = None,
    ) -> AsyncIterator[str | ToolCall]:
        messages = self._truncate_messages(messages)
        from google.genai import types

        converted = self._convert_messages(messages)
        kwargs: dict = {"model": self.model_id, "contents": converted}
        converted_tools = self._convert_tools(tools)

        config_kwargs: dict = {}
        if converted_tools:
            config_kwargs["tools"] = converted_tools
        if response_format:
            schema = response_format.get("json_schema", {}).get("schema", {})
            config_kwargs["response_mime_type"] = "application/json"
            if schema:
                config_kwargs["response_schema"] = _sanitize_gemini_schema(schema)
        if config_kwargs:
            kwargs["config"] = types.GenerateContentConfig(**config_kwargs)

        try:
            async for chunk in await self._client.aio.models.generate_content_stream(**kwargs):
                if chunk.text:
                    yield chunk.text
                if chunk.candidates and chunk.candidates[0].content.parts:
                    for part in chunk.candidates[0].content.parts:
                        if part.function_call:
                            yield ToolCall(
                                id=f"fc_{uuid.uuid4().hex[:8]}",
                                name=part.function_call.name,
                                arguments=dict(part.function_call.args) if part.function_call.args else {},
                                thought_signature=getattr(part, "thought_signature", None),
                            )
        except Exception as e:
            raise LLMError(f"Google streaming error: {e}", provider="google", original_error=e)




class OllamaClient(LLMClient):
    def __init__(
        self,
        model: str,
        base_url: Optional[str] = None,
        config: Optional[LLMConfig] = None,
    ):
        super().__init__(model, config, provider="ollama")
        from ollama import AsyncClient

        self._client = AsyncClient(host=base_url)
        self.base_url = base_url

    def _convert_messages(self, messages: list[ChatMessage]) -> list[dict]:
        result = []
        for msg in messages:
            if msg.role == "tool":
                # Ollama maps function responses using role="tool"
                result.append({
                    "role": "tool",
                    "content": msg.content or "",
                })
            elif msg.tool_calls:
                tool_calls = [
                    {
                        "function": {
                            "name": tc.name,
                            "arguments": tc.arguments
                        }
                    }
                    for tc in msg.tool_calls
                ]
                result.append({
                    "role": msg.role,
                    "content": msg.content or "",
                    "tool_calls": tool_calls,
                })
            elif msg.images:
                images = []
                for img_url in msg.images:
                    if img_url.startswith("data:"):
                        b64 = img_url.split(",", 1)[-1]
                        images.append(b64)
                    else:
                        images.append(img_url)

                result.append({
                    "role": msg.role,
                    "content": msg.content or "",
                    "images": images
                })
            else:
                result.append({
                    "role": msg.role,
                    "content": msg.content or ""
                })
        return result

    def _convert_tools(self, tools: Optional[list[dict]]) -> Optional[list[dict]]:
        if not tools:
            return None
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("parameters", {}),
                }
            }
            for t in tools
        ]

    async def chat(
        self,
        messages: list[ChatMessage],
        tools: Optional[list[dict]] = None,
        tool_choice: Optional[str] = None,
        response_format: Optional[dict] = None,
    ) -> ChatMessage:
        messages = self._truncate_messages(messages)

        async def _make_request():
            kwargs: dict = {
                "model": self.model,
                "messages": self._convert_messages(messages),
            }

            options = {}
            if self.config.temperature is not None:
                options["temperature"] = self.config.temperature
            if self.config.top_p is not None:
                options["top_p"] = self.config.top_p
            if self.config.stop is not None:
                options["stop"] = self.config.stop

            if options:
                kwargs["options"] = options

            if tools:
                kwargs["tools"] = self._convert_tools(tools)

            response = await self._client.chat(**kwargs)
            message = response.get("message", {})

            tool_calls = []
            if "tool_calls" in message and message["tool_calls"]:
                for tc in message["tool_calls"]:
                    func = tc.get("function", {})
                    if func:
                        tool_calls.append(
                            ToolCall(
                                id=f"call_{uuid.uuid4().hex}",
                                name=func.get("name", ""),
                                arguments=func.get("arguments", {}),
                            )
                        )

            return ChatMessage(
                role=message.get("role", "assistant"),
                content=message.get("content", ""),
                tool_calls=tool_calls,
            )

        try:
            return await self._retry_with_backoff(_make_request)
        except LLMError:
            raise
        except Exception as e:
            raise LLMError(f"Ollama API error: {e}", provider="ollama", original_error=e)

    async def chat_stream(
        self,
        messages: list[ChatMessage],
        tools: Optional[list[dict]] = None,
        tool_choice: Optional[str] = None,
    ) -> AsyncIterator[str | ToolCall]:
        messages = self._truncate_messages(messages)
        kwargs: dict = {
            "model": self.model,
            "messages": self._convert_messages(messages),
            "stream": True,
        }

        options = {}
        if self.config.temperature is not None:
            options["temperature"] = self.config.temperature
        if self.config.top_p is not None:
            options["top_p"] = self.config.top_p
        if self.config.stop is not None:
            options["stop"] = self.config.stop

        if options:
            kwargs["options"] = options

        if tools:
            kwargs["tools"] = self._convert_tools(tools)

        try:
            async for chunk in await self._client.chat(**kwargs):
                message = chunk.get("message", {})

                if "tool_calls" in message and message["tool_calls"]:
                    for tc in message["tool_calls"]:
                        func = tc.get("function", {})
                        if func:
                            yield ToolCall(
                                id=f"call_{uuid.uuid4().hex}",
                                name=func.get("name", ""),
                                arguments=func.get("arguments", {}),
                            )

                content = message.get("content", "")
                if content:
                    yield content
        except Exception as e:
            raise LLMError(f"Ollama streaming error: {e}", provider="ollama", original_error=e)

PROVIDER_API_KEYS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
    "google-genai": "GOOGLE_API_KEY",
    "google-vertex": "GOOGLE_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "groq": "GROQ_API_KEY",
    "cerebras": "CEREBRAS_API_KEY",
    "perplexity": "PERPLEXITY_API_KEY",
    "together": "TOGETHER_API_KEY",
    "togetherai": "TOGETHER_API_KEY",
    "fireworks": "FIREWORKS_API_KEY",
    "xai": "XAI_API_KEY",
    "cohere": "CO_API_KEY",
    "openai-compatible": "OPENAI_COMPATIBLE_API_KEY",
}


_TRANSPORT_PROVIDERS = frozenset({"openai-compatible", "ollama"})

_PROVIDER_ALIASES: dict[str, str] = {
    "google-genai": "google",
    "google_gemini": "google",
}

_UNSUPPORTED_EMBEDDING_PROVIDERS = frozenset({
    "sentence-transformer",
    "sentence-transformers",
})

_LEGACY_SENTENCE_TRANSFORMER_MODELS = frozenset({
    "all-minilm-l6-v2",
    "all-minilm-l12-v2",
    "all-mpnet-base-v2",
    "paraphrase-minilm-l6-v2",
    "paraphrase-multilingual-minilm-l12-v2",
    "baai/bge-small-en-v1.5",
    "baai/bge-base-en-v1.5",
    "baai/bge-large-en-v1.5",
})


def _normalize_provider(provider: str) -> str:
    return _PROVIDER_ALIASES.get(provider, provider)


def _is_sentence_transformer_provider(value: Optional[str]) -> bool:
    if not value:
        return False
    return value.lower().replace("_", "-") in _UNSUPPORTED_EMBEDDING_PROVIDERS


def _is_legacy_sentence_transformer_model(value: Optional[str]) -> bool:
    if not value:
        return False
    model = value.lower().replace("_", "-")
    return model in _LEGACY_SENTENCE_TRANSFORMER_MODELS


def _reject_sentence_transformer_embeddings(model: str, provider: Optional[str]) -> None:
    if _is_sentence_transformer_provider(provider):
        raise ValueError(
            "sentence-transformers embeddings are no longer supported; "
            "use ollama, google, google-vertex, or openai-compatible instead."
        )

    if "/" in model:
        prefix = model.split("/", 1)[0]
        if _is_sentence_transformer_provider(prefix):
            raise ValueError(
                "sentence-transformers embeddings are no longer supported; "
                "use ollama, google, google-vertex, or openai-compatible instead."
            )

    if _is_legacy_sentence_transformer_model(model):
        raise ValueError(
            "legacy sentence-transformer embedding models are no longer supported; "
            "use an Ollama, Google, Vertex, or OpenAI-compatible embedding model instead."
        )


def _detect_provider_from_model(model: str) -> str:
    model_lower = model.lower()
    if any(x in model_lower for x in ["gpt-", "o1-", "o3-", "o4-", "chatgpt"]):
        return "openai"
    elif "claude" in model_lower:
        return "anthropic"
    elif "gemini" in model_lower or "google" in model_lower:
        if "vertex" in model_lower:
            return "google-vertex"
        return "google"
    elif "deepseek" in model_lower:
        return "deepseek"
    elif "mistral" in model_lower or "mixtral" in model_lower:
        return "mistral"
    elif "llama" in model_lower:
        if "meta" in model_lower or "facebook" in model_lower:
            return "together"
        for provider in ["together", "fireworks", "groq", "deepinfra"]:
            if provider in PROVIDER_URLS:
                return provider
        return "together"
    elif "qwen" in model_lower:
        return "alibaba"
    elif "grok" in model_lower:
        return "xai"
    return "openai"


def resolve_provider_and_model(
    model: str,
    provider: Optional[str] = None,
) -> tuple[str, str, Optional[str]]:
    """Single source of truth for resolving provider and model.

    Parses ``provider/model`` format, normalises provider aliases, and
    returns a triple of ``(effective_provider, clean_model, model_provider)``.

    * ``effective_provider`` — the *transport* that routes the request
      (e.g. ``"openai-compatible"``, ``"ollama"``, or a native provider
      like ``"google-vertex"``).
    * ``clean_model`` — the bare model identifier with any ``provider/``
      prefix always stripped.  When the effective provider is a transport
      (openai-compatible, ollama), the original ``model`` string (with
      prefix intact) is passed directly to the client constructor instead.
    * ``model_provider`` — the provider embedded in the model string
      (e.g. ``"google-vertex"`` from ``"google-vertex/gemini-3.1-flash"``).
      ``None`` when the model string has no ``provider/`` prefix.

    Resolution order:
      1. If *provider* is given and is a transport provider, keep it as
         the effective provider.  Parse any ``provider/`` prefix from the
         model to populate ``model_provider`` but **do not** strip it from
         ``clean_model`` (the transport server needs it).
      2. If the model starts with ``provider/`` and *provider* is not given,
         extract the prefix as both the effective provider and
         ``model_provider``, and strip it from ``clean_model``.
      3. If neither (1) nor (2) applies, auto-detect the provider from the
         model name.
    """
    _KNOWN_PROVIDERS = frozenset({
        "openai", "anthropic", "google", "google-genai", "google_gemini",
        "google-vertex", "deepseek", "mistral", "groq", "cerebras",
        "perplexity", "together", "togetherai", "fireworks", "xai",
        "cohere", "alibaba", "ollama", "openai-compatible",
    })

    model_provider: Optional[str] = None
    rest: str = model

    if "/" in model:
        prefix, rest = model.split("/", 1)
        if prefix and _normalize_provider(prefix) in _KNOWN_PROVIDERS:
            model_provider = _normalize_provider(prefix)

    if provider is not None:
        effective = _normalize_provider(provider)
    elif model_provider is not None:
        effective = model_provider
    else:
        effective = _detect_provider_from_model(model)

    if model_provider is not None:
        clean_model = rest
    else:
        clean_model = model

    return effective, clean_model, model_provider


def _resolve_transport_api_key(provider: Optional[str]) -> Optional[str]:
    if not provider:
        return None

    env_name = PROVIDER_API_KEYS.get(provider)
    if env_name:
        val = os.environ.get(env_name)
        if val:
            return val

    auth_path = Path.home() / ".local" / "share" / "opencode" / "auth.json"
    if auth_path.exists():
        try:
            auth_data = json.loads(auth_path.read_text())
            entry = auth_data.get(provider)
            if isinstance(entry, dict) and entry.get("type") == "api":
                return entry.get("key")
        except Exception as e:
            logger.warning("[OPENCODE_MODELS] auth.json read failed: %s", e)

    return None


def create_client(
    model: str,
    provider: Optional[str] = None,
    api_key: Optional[str] = None,
    config: Optional[LLMConfig] = None,
    base_url: Optional[str] = None,
) -> LLMClient:
    effective_provider, clean_model, model_provider = resolve_provider_and_model(model, provider)

    try:
        from dashboard.lib.settings.resolver import get_settings_resolver
        resolver = get_settings_resolver()
        master_settings = resolver.get_master_settings()
        providers = master_settings.providers if master_settings else None
    except Exception:
        providers = None

    if effective_provider in ("google", "google-vertex"):
        resolved_base_url = base_url or _get_base_url(effective_provider)
        is_vertex = effective_provider == "google-vertex"
        if is_vertex and resolved_base_url:
            region = os.environ.get("VERTEX_LOCATION", "global")
            project = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
            resolved_base_url = resolved_base_url.replace("{region}", region).replace("{project}", project)
        resolved_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        return GoogleClient(model=clean_model, api_key=resolved_key, base_url=resolved_base_url, config=config, vertexai=is_vertex, provider=effective_provider)

    if effective_provider == "ollama":
        cfg = providers.ollama if providers else None
        resolved_base_url = base_url or (cfg.base_url if cfg and cfg.base_url else os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"))
        return OllamaClient(model=model, base_url=resolved_base_url, config=config)

    resolved_base_url = base_url or _get_base_url(effective_provider)
    resolved_key = api_key or _resolve_transport_api_key(effective_provider)
    return OpenAIClient(model=model, api_key=resolved_key, base_url=resolved_base_url, config=config, provider=effective_provider)


# ---------------------------------------------------------------------------
# Sync helper — run an async coroutine from sync code
# ---------------------------------------------------------------------------

def run_sync(coro):
    """Execute an async coroutine from synchronous code.

    If no event loop is running, uses ``asyncio.run()``.  If a loop is
    already running (e.g. inside ``asyncio.to_thread``), spins up a new
    loop in a dedicated thread so we don't collide with the existing one.

    This is the shared version of the ``_run_sync`` helpers that were
    duplicated in ``dashboard.knowledge.llm`` and elsewhere.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    # Already inside a loop → use a thread-based loop
    import concurrent.futures

    def _runner():
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(_runner).result()


def create_openai_sync_client(
    model: str,
    provider: Optional[str] = None,
    api_key: Optional[str] = None,
    timeout: float = REQUEST_TIMEOUT,
) -> Optional["OpenAI"]:
    """Create a sync OpenAI SDK client for any provider.

    Uses the same ``resolve_provider_and_model`` pipeline as
    :func:`create_client` so provider prefixes (e.g. ``"google/gemini-2.0-flash"``)
    and aliases are resolved correctly.  Returns a ``openai.OpenAI`` sync
    client configured with the resolved ``base_url`` and ``api_key``,
    making it compatible with MarkItDown's ``ImageConverter`` and any
    other library that expects the standard OpenAI SDK interface.

    For Google/Gemini models, uses Gemini's OpenAI-compatible endpoint
    (``https://generativelanguage.googleapis.com/v1beta/openai/``).
    For Ollama, uses the Ollama OpenAI-compatible endpoint.

    Returns ``None`` when no API key can be resolved (graceful degradation).
    """
    effective_provider, clean_model, model_provider = resolve_provider_and_model(model, provider)

    resolved_key = api_key

    if effective_provider in ("google", "google-vertex"):
        base_url = _get_base_url(effective_provider) or GoogleClient._GEMINI_OPENAI_BASE
        if not resolved_key:
            resolved_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    elif effective_provider == "ollama":
        try:
            from dashboard.lib.settings.resolver import get_settings_resolver
            resolver = get_settings_resolver()
            master_settings = resolver.get_master_settings()
            cfg = master_settings.providers.ollama if master_settings else None
            base_url = cfg.base_url if cfg and cfg.base_url else os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        except Exception:
            base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        if not resolved_key:
            resolved_key = "ollama"
    else:
        base_url = _get_base_url(effective_provider)
        if not resolved_key:
            resolved_key = _resolve_transport_api_key(effective_provider)

    if not resolved_key:
        return None

    try:
        from openai import OpenAI
        return OpenAI(api_key=resolved_key, base_url=base_url, timeout=timeout)
    except Exception as exc:
        logger.warning("Failed to create OpenAI sync client for %s: %s", model, exc)
        return None


# Single source of truth for embedding dimension across the entire system.
# Fixed at startup from OSTWIN_EMBEDDING_DIM env var; cannot be changed
# dynamically via settings.  All embedding clients, vector stores, and
# retrievers (memory + knowledge) MUST use this value to avoid dimension
# conflicts in shared collections.
DEFAULT_EMBEDDING_DIMENSION: int = int(
    os.environ.get("OSTWIN_EMBEDDING_DIM", "1024")
)

# ---------------------------------------------------------------------------
# Embedding client abstraction
# ---------------------------------------------------------------------------

# Known native model dimensions — avoids a test-embedding probe on first use.
_KNOWN_EMBEDDING_DIMENSIONS: dict[str, int] = {
    "gemini-embedding-001": DEFAULT_EMBEDDING_DIMENSION,
    "text-embedding-004": DEFAULT_EMBEDDING_DIMENSION,
    "text-embedding-005": DEFAULT_EMBEDDING_DIMENSION,
    "text-embedding-3-small": DEFAULT_EMBEDDING_DIMENSION,
    "text-embedding-3-large": DEFAULT_EMBEDDING_DIMENSION,
    "leoipulsar/harrier-0.6b": DEFAULT_EMBEDDING_DIMENSION,
    "embeddinggemma": DEFAULT_EMBEDDING_DIMENSION,
    "qwen3-embedding:0.6b": DEFAULT_EMBEDDING_DIMENSION,
    "qwen3-embedding:4b": DEFAULT_EMBEDDING_DIMENSION,
}


class EmbeddingClient(ABC):
    """Base class for embedding providers.

    Subclasses implement ``embed(texts)`` which returns a list of float-lists.
    The ``dimension`` property returns the output vector size (cached on first
    call when not explicitly set).
    """

    def __init__(self, model: str, dimension: Optional[int] = None):
        self.model = model
        self._dimension = dimension

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts. Returns a list of float-lists."""

    def embed_one(self, text: str) -> list[float]:
        """Embed a single text string."""
        if text is None:
            return []
        result = self.embed([text])
        return result[0] if result else []

    @property
    def dimension(self) -> int:
        """Return the embedding dimension (cached after first probe)."""
        if self._dimension is not None:
            return self._dimension
        # Probe once and cache
        try:
            probe = self.embed_one("dimension probe")
            self._dimension = len(probe) if probe else DEFAULT_EMBEDDING_DIMENSION
        except Exception:
            self._dimension = DEFAULT_EMBEDDING_DIMENSION
        return self._dimension

    @staticmethod
    def _truncate_to_dim(embeddings: list[list[float]], dim: int) -> list[list[float]]:
        """Truncate (or zero-pad) each vector to exactly *dim* floats.

        Truncation of MRL (Matryoshka Representation Learning) models is
        dimension-preserving: the first *dim* components retain full semantic
        quality.  Zero-padding is a lossy fallback for models whose native
        dimension is smaller than the target.
        """
        out: list[list[float]] = []
        for vec in embeddings:
            if len(vec) >= dim:
                out.append(vec[:dim])
            else:
                out.append(vec + [0.0] * (dim - len(vec)))
        return out


class OllamaEmbeddingClient(EmbeddingClient):
    """Ollama embedding via the native ``ollama`` Python SDK.

    No litellm dependency.  Output is truncated to the configured dimension
    (default: 1024) for cross-backend consistency.
    """

    def __init__(
        self,
        model: str,
        base_url: Optional[str] = None,
        dimension: Optional[int] = None,
    ):
        super().__init__(model, dimension)
        self._base_url = base_url  # None → ollama default (localhost:11434)

    def embed(self, texts: list[str]) -> list[list[float]]:
        import ollama as _ollama  # noqa: WPS433

        if not texts:
            return []
        kwargs: dict = {"model": self.model, "input": texts}
        if self._dimension is not None:
            kwargs["dimensions"] = self._dimension
        try:
            response = _ollama.embed(**kwargs)
            result = response["embeddings"]
        except Exception as exc:
            logger.error("Ollama embedding failed: %s", exc)
            return [[] for _ in texts]

        target_dim = self._dimension or DEFAULT_EMBEDDING_DIMENSION
        return self._truncate_to_dim(result, target_dim)


class OpenAICompatibleEmbeddingClient(EmbeddingClient):
    """Embedding via any OpenAI-compatible /v1/embeddings endpoint.

    Uses ``OPENAI_COMPATIBLE_BASE_URL`` and ``OPENAI_COMPATIBLE_API_KEY``
    env vars when not explicitly set.
    """

    def __init__(
        self,
        model: str,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        dimension: Optional[int] = None,
    ):
        super().__init__(model, dimension)
        self._base_url = base_url
        self._api_key = api_key

    def embed(self, texts: list[str]) -> list[list[float]]:
        import httpx

        if not texts:
            return []

        base_url = self._base_url or os.environ.get(
            "OPENAI_COMPATIBLE_BASE_URL", "http://localhost:8000"
        )
        api_key = self._api_key or os.environ.get("OPENAI_COMPATIBLE_API_KEY", "")

        try:
            with httpx.Client() as client:
                payload: dict = {"model": self.model, "input": texts}
                if self._dimension is not None:
                    payload["dimensions"] = self._dimension
                response = client.post(
                    f"{base_url}/v1/embeddings",
                    headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
                    json=payload,
                    timeout=60.0,
                )
                response.raise_for_status()
                data = response.json()
                result = [item["embedding"] for item in data["data"]]
        except Exception as exc:
            logger.error("OpenAI-compatible embedding failed: %s", exc)
            return [[] for _ in texts]

        target_dim = self._dimension or DEFAULT_EMBEDDING_DIMENSION
        return self._truncate_to_dim(result, target_dim)


class GeminiEmbeddingClient(EmbeddingClient):
    """Embedding via Google Gemini / Vertex AI embedding API.

    Uses the ``google-genai`` SDK (same as ``GoogleClient`` for chat).
    Supports both AI Studio (api_key) and Vertex AI (project + location).
    """

    def __init__(
        self,
        model: str = "gemini-embedding-001",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        dimension: Optional[int] = None,
        vertexai: bool = False,
    ):
        super().__init__(model, dimension)
        from google.genai import Client

        if vertexai:
            project = os.environ.get("GOOGLE_CLOUD_PROJECT")
            location = os.environ.get("VERTEX_LOCATION")
            self._client = Client(vertexai=True, project=project, location=location)
        else:
            key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
            self._client = Client(api_key=key)
        self._base_url = base_url

    def embed(self, texts: list[str]) -> list[list[float]]:
        from google.genai import types

        if not texts:
            return []
        try:
            # The genai SDK supports batch embedding
            result = self._client.models.embed_content(
                model=self.model,
                contents=texts,
                config=types.EmbedContentConfig(
                    output_dimensionality=self._dimension,
                ) if self._dimension is not None else None,
            )
            embeddings = [e.values for e in result.embeddings]
        except Exception as exc:
            logger.error("Gemini embedding failed: %s", exc)
            return [[] for _ in texts]

        target_dim = self._dimension or DEFAULT_EMBEDDING_DIMENSION
        return self._truncate_to_dim(embeddings, target_dim)


# Embedding-client singleton cache: keyed by (provider, model, dimension)
_embedding_cache: dict[str, Any] = {}
_embedding_cache_lock = threading.Lock()


def _detect_embedding_provider_from_model(model: str) -> str:
    """Auto-detect embedding provider from a bare model name (no provider/ prefix).

    Mirrors the logic in ``_detect_provider_from_model`` but returns embedding-
    specific provider identifiers (e.g. ``"ollama"`` instead of ``"openai"``).
    """
    if not model:
        return "ollama"
    if _is_legacy_sentence_transformer_model(model):
        raise ValueError(
            "legacy sentence-transformer embedding models are no longer supported; "
            "use an Ollama, Google, Vertex, or OpenAI-compatible embedding model instead."
        )
    model_lower = model.lower()
    if "gemini" in model_lower or "text-embedding" in model_lower:
        if "vertex" in model_lower:
            return "google-vertex"
        return "google"
    if any(x in model_lower for x in ["gpt-", "text-embedding-3"]):
        return "openai-compatible"
    return "ollama"


def create_embedding_client(
    model: str,
    provider: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    dimension: Optional[int] = None,
    *,
    shared: bool = True,
) -> EmbeddingClient:
    """Factory: create (or retrieve cached) embedding client.

    Uses the same ``resolve_provider_and_model`` pipeline as ``create_client``
    so that ``provider/model`` prefixes (e.g. ``"google-vertex/gemini-embedding-001"``)
    are parsed, aliases normalised, and the provider prefix stripped from the
    model name before construction.

    Args:
        model: Embedding model identifier.  May include a ``provider/`` prefix
            (e.g. ``"google-vertex/gemini-embedding-001"``).
        provider: Backend: ``"ollama"``, ``"google"``, ``"google-vertex"``,
            or ``"openai-compatible"``. Auto-detected from model name when ``None``.
        api_key: API key (provider-specific).
        base_url: Override base URL for the provider.
        dimension: Output vector dimension.  ``None`` means use the model's
            native dimension (or ``DEFAULT_EMBEDDING_DIMENSION`` as fallback).
        shared: If ``True`` (default), return a singleton cached by
            ``(provider, model, dimension)``.  ``False`` creates a private
            instance.

    Returns:
        An ``EmbeddingClient`` instance.
    """
    _reject_sentence_transformer_embeddings(model, provider)
    effective_provider, clean_model, model_provider = resolve_provider_and_model(model, provider)

    # model_provider (from "provider/model" prefix) is the strongest signal —
    # the user explicitly chose this provider for this model.  Fall back to
    # effective_provider only when no prefix was present.
    embed_provider = model_provider if model_provider is not None else effective_provider

    # Use the embedding-specific provider detector for models without an
    # explicit provider prefix.  The chat-oriented _detect_provider_from_model
    # misroutes Ollama models (e.g. "leoipulsar/harrier-0.6b" → "openai")
    # because Ollama model names don't follow chat model naming conventions.
    if model_provider is None and provider is None:
        embed_provider = _detect_embedding_provider_from_model(clean_model)

    _CHAT_TO_EMBED_PROVIDER: dict[str, str] = {
        "openai": "openai-compatible",
        "anthropic": "openai-compatible",
        "deepseek": "openai-compatible",
        "mistral": "openai-compatible",
        "groq": "openai-compatible",
        "cerebras": "openai-compatible",
        "perplexity": "openai-compatible",
        "together": "openai-compatible",
        "togetherai": "openai-compatible",
        "fireworks": "openai-compatible",
        "xai": "openai-compatible",
        "cohere": "openai-compatible",
        "alibaba": "openai-compatible",
    }

    if embed_provider in _CHAT_TO_EMBED_PROVIDER:
        embed_provider = _CHAT_TO_EMBED_PROVIDER[embed_provider]
    elif embed_provider == "ollama":
        pass
    elif embed_provider in ("google", "google-vertex"):
        pass
    elif embed_provider == "openai-compatible":
        pass
    else:
        embed_provider = _detect_embedding_provider_from_model(clean_model)

    # Use known dimension if not explicitly set
    if dimension is None:
        dimension = _KNOWN_EMBEDDING_DIMENSIONS.get(clean_model)

    cache_key = f"{embed_provider}:{clean_model}:{dimension}"

    if shared:
        with _embedding_cache_lock:
            cached = _embedding_cache.get(cache_key)
            if cached is not None:
                return cached

    try:
        from dashboard.lib.settings.resolver import get_settings_resolver
        resolver = get_settings_resolver()
        master_settings = resolver.get_master_settings()
        providers_cfg = master_settings.providers if master_settings else None
    except Exception:
        providers_cfg = None

    if model_provider in ("google", "google-genai", "google_gemini", "google-vertex"):
        is_vertex = embed_provider == "google-vertex"
        resolved_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        client = GeminiEmbeddingClient(
            model=clean_model,
            api_key=resolved_key,
            base_url=base_url,
            dimension=dimension,
            vertexai=is_vertex,
        )
    elif embed_provider == "openai-compatible" and embed_provider != model_provider:
        cfg = providers_cfg.openai_compatible if providers_cfg else None
        resolved_base = base_url or (
            cfg.base_url if cfg and cfg.base_url else os.environ.get(
                "OPENAI_COMPATIBLE_BASE_URL", "http://localhost:8000"
            )
        )
        resolved_key = api_key or _resolve_transport_api_key(model_provider)
        client = OpenAICompatibleEmbeddingClient(
            model=clean_model,
            base_url=resolved_base,
            api_key=resolved_key,
            dimension=dimension,
        )
    elif embed_provider == "ollama" or provider == "ollama":
        cfg = providers_cfg.ollama if providers_cfg else None
        resolved_base = base_url or (
            cfg.base_url if cfg and cfg.base_url else os.environ.get(
                "OLLAMA_BASE_URL", "http://localhost:11434"
            )
        )
        client = OllamaEmbeddingClient(
            model=clean_model,
            base_url=resolved_base,
            dimension=dimension,
        )
    else:
        logger.warning("Unknown embedding provider %r; falling back to ollama", embed_provider)
        client = OllamaEmbeddingClient(
            model=clean_model,
            base_url=base_url,
            dimension=dimension,
        )

    if shared:
        with _embedding_cache_lock:
            existing = _embedding_cache.get(cache_key)
            if existing is not None:
                return existing
            _embedding_cache[cache_key] = client

    return client
