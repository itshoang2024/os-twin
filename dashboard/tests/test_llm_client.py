"""
Unit tests for llm_client.py multi-provider LLM abstraction.
"""

import asyncio
import json
import pytest
import sys
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

# Mock google.genai before importing llm_client
mock_google_genai = MagicMock()
mock_google_types = MagicMock()
sys.modules["google.genai"] = mock_google_genai
sys.modules["google.genai.types"] = mock_google_types

from dashboard.llm_client import (
    ToolCall,
    ChatMessage,
    LLMClient,
    LLMConfig,
    LLMError,
    OpenAIClient,
    GoogleClient,
    create_client,
    _detect_provider_from_model,
    _get_base_url,
    load_provider_urls,
    PROVIDER_URLS,
    _sanitize_gemini_schema,
    _GEMINI_SCHEMA_ALLOWED_KEYS,
    _detect_embedding_provider_from_model,
    create_embedding_client,
    OllamaEmbeddingClient,
    OpenAICompatibleEmbeddingClient,
    GeminiEmbeddingClient,
)


class TestToolCall:
    def test_tool_call_repr(self):
        tc = ToolCall(id="call_123", name="get_weather", arguments={"city": "London"})
        assert repr(tc) == "ToolCall(id='call_123', name='get_weather')"

    def test_tool_call_default_arguments(self):
        tc = ToolCall(id="call_456", name="search")
        assert tc.arguments == {}


class TestChatMessage:
    def test_chat_message_repr(self):
        msg = ChatMessage(role="user", content="Hello world!")
        assert "ChatMessage" in repr(msg)
        assert "user" in repr(msg)

    def test_chat_message_with_tool_calls(self):
        tc = ToolCall(id="tc1", name="test_tool", arguments={"x": 1})
        msg = ChatMessage(role="assistant", content="Result", tool_calls=[tc])
        assert len(msg.tool_calls) == 1
        assert msg.tool_calls[0].name == "test_tool"

    def test_chat_message_tool_response(self):
        msg = ChatMessage(
            role="tool",
            content="Tool result",
            tool_call_id="tc_123",
            name="get_weather"
        )
        assert msg.role == "tool"
        assert msg.tool_call_id == "tc_123"
        assert msg.name == "get_weather"


class TestLLMConfig:
    def test_default_config(self):
        config = LLMConfig()
        assert config.max_tokens is None
        assert config.temperature is None
        assert config.top_p is None
        assert config.stop is None

    def test_custom_config(self):
        config = LLMConfig(max_tokens=8192, temperature=0.7, stop=["END"])
        assert config.max_tokens == 8192
        assert config.temperature == 0.7
        assert config.stop == ["END"]


class TestDetectProviderFromModel:
    def test_openai_models(self):
        assert _detect_provider_from_model("gpt-4") == "openai"
        assert _detect_provider_from_model("gpt-3.5-turbo") == "openai"
        assert _detect_provider_from_model("o1-preview") == "openai"
        assert _detect_provider_from_model("o3-mini") == "openai"
        assert _detect_provider_from_model("O4-MINI") == "openai"

    def test_anthropic_models(self):
        assert _detect_provider_from_model("claude-3-opus") == "anthropic"
        assert _detect_provider_from_model("claude-sonnet-4") == "anthropic"
        assert _detect_provider_from_model("CLAUDE-3-HAIKU") == "anthropic"

    def test_google_models(self):
        assert _detect_provider_from_model("gemini-pro") == "google"
        assert _detect_provider_from_model("gemini-2-flash") == "google"
        assert _detect_provider_from_model("GEMINI-ULTRA") == "google"

    def test_deepseek_models(self):
        assert _detect_provider_from_model("deepseek-coder") == "deepseek"
        assert _detect_provider_from_model("deepseek-chat") == "deepseek"

    def test_mistral_models(self):
        assert _detect_provider_from_model("mistral-large") == "mistral"
        assert _detect_provider_from_model("mixtral-8x7b") == "mistral"

    def test_llama_models(self):
        provider = _detect_provider_from_model("llama-3-70b")
        assert provider in ["together", "fireworks", "groq", "deepinfra"]

    def test_unknown_model_defaults_to_openai(self):
        assert _detect_provider_from_model("unknown-model") == "openai"


class TestGetBaseUrl:
    def test_hardcoded_providers(self):
        assert _get_base_url("openai") == "https://api.openai.com/v1"
        assert _get_base_url("anthropic") == "https://api.anthropic.com/v1"
        assert _get_base_url("deepseek") == "https://api.deepseek.com"

    def test_provider_from_urls_json(self):
        if "xai" in PROVIDER_URLS:
            assert _get_base_url("xai") == PROVIDER_URLS["xai"]["base"]

    def test_unknown_provider(self):
        assert _get_base_url("unknown_provider_xyz") is None


class TestLoadProviderUrls:
    def test_loads_valid_json(self):
        urls = load_provider_urls()
        assert isinstance(urls, dict)
        assert "openai" in urls
        assert urls["openai"]["base"] == "https://api.openai.com/v1"


class TestOpenAIClient:
    def test_init(self):
        with patch("openai.AsyncOpenAI") as MockAsyncOpenAI:
            MockAsyncOpenAI.return_value = MagicMock()
            client = OpenAIClient(model="gpt-4", api_key="test-key")
            assert client.model == "gpt-4"

    def test_convert_messages_simple(self):
        with patch("openai.AsyncOpenAI") as MockAsyncOpenAI:
            MockAsyncOpenAI.return_value = MagicMock()
            client = OpenAIClient(model="gpt-4", api_key="test")
            messages = [
                ChatMessage(role="system", content="You are helpful."),
                ChatMessage(role="user", content="Hello"),
            ]
            converted = client._convert_messages(messages)
            assert len(converted) == 2
            assert converted[0]["role"] == "system"
            assert converted[1]["role"] == "user"

    def test_convert_messages_with_tool_response(self):
        with patch("openai.AsyncOpenAI") as MockAsyncOpenAI:
            MockAsyncOpenAI.return_value = MagicMock()
            client = OpenAIClient(model="gpt-4", api_key="test")
            messages = [
                ChatMessage(role="assistant", content="Let me check.", tool_calls=[
                    ToolCall(id="tc_1", name="get_weather", arguments={"city": "NYC"})
                ]),
                ChatMessage(role="tool", content="Sunny, 72F", tool_call_id="tc_1"),
            ]
            converted = client._convert_messages(messages)
            assert len(converted) == 2
            assert converted[1]["role"] == "tool"
            assert converted[1]["tool_call_id"] == "tc_1"
            assert converted[1]["content"] == "Sunny, 72F"

    def test_convert_tools(self):
        with patch("openai.AsyncOpenAI") as MockAsyncOpenAI:
            MockAsyncOpenAI.return_value = MagicMock()
            client = OpenAIClient(model="gpt-4", api_key="test")
            tools = [
                {"name": "get_weather", "description": "Get weather", "parameters": {}}
            ]
            converted = client._convert_tools(tools)
            assert len(converted) == 1
            assert converted[0]["type"] == "function"
            assert converted[0]["function"]["name"] == "get_weather"

    @pytest.mark.asyncio
    async def test_chat_with_mock(self):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Hello there!"
        mock_response.choices[0].message.role = "assistant"
        mock_response.choices[0].message.tool_calls = None

        with patch("openai.AsyncOpenAI") as MockAsyncOpenAI:
            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            MockAsyncOpenAI.return_value = mock_client

            client = OpenAIClient(model="gpt-4", api_key="test")
            messages = [ChatMessage(role="user", content="Hi")]
            result = await client.chat(messages)

            assert result.content == "Hello there!"
            assert result.role == "assistant"

    @pytest.mark.asyncio
    async def test_chat_with_tool_calls(self):
        mock_tc = MagicMock()
        mock_tc.id = "tc_123"
        mock_tc.function.name = "get_weather"
        mock_tc.function.arguments = '{"city": "London"}'

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = None
        mock_response.choices[0].message.role = "assistant"
        mock_response.choices[0].message.tool_calls = [mock_tc]

        with patch("openai.AsyncOpenAI") as MockAsyncOpenAI:
            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            MockAsyncOpenAI.return_value = mock_client

            client = OpenAIClient(model="gpt-4", api_key="test")
            messages = [ChatMessage(role="user", content="What's the weather?")]
            result = await client.chat(messages)

            assert len(result.tool_calls) == 1
            assert result.tool_calls[0].name == "get_weather"
            assert result.tool_calls[0].arguments == {"city": "London"}

    @pytest.mark.asyncio
    async def test_chat_retry_on_failure(self):
        call_count = 0

        async def failing_create(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception("API Error")
            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]
            mock_response.choices[0].message.content = "Success"
            mock_response.choices[0].message.role = "assistant"
            mock_response.choices[0].message.tool_calls = None
            return mock_response

        with patch("openai.AsyncOpenAI") as MockAsyncOpenAI:
            mock_client = AsyncMock()
            mock_client.chat.completions.create = failing_create
            MockAsyncOpenAI.return_value = mock_client

            client = OpenAIClient(model="gpt-4", api_key="test")
            messages = [ChatMessage(role="user", content="Hi")]
            result = await client.chat(messages)

            assert call_count == 3
            assert result.content == "Success"


class TestGoogleClient:
    def test_init(self):
        mock_client = MagicMock()
        with patch.object(mock_google_genai, "Client", return_value=mock_client):
            client = GoogleClient(model="gemini-pro", api_key="test-key")
            assert client.model == "gemini-pro"

    def test_convert_messages_simple(self):
        mock_types = MagicMock()
        mock_content = MagicMock()
        mock_part = MagicMock()
        mock_types.Content = mock_content
        mock_types.Part = mock_part
        
        with patch.object(mock_google_genai, "types", mock_types):
            with patch.object(mock_google_genai, "Client"):
                client = GoogleClient(model="gemini-pro", api_key="test")
                messages = [
                    ChatMessage(role="system", content="You are helpful."),
                    ChatMessage(role="user", content="Hello"),
                ]
                converted = client._convert_messages(messages)
                assert len(converted) == 2

    def test_convert_messages_with_tool_response(self):
        mock_types = MagicMock()
        mock_types.Content = MagicMock(return_value=MagicMock())
        mock_types.Part = MagicMock()
        mock_types.FunctionResponse = MagicMock(return_value=MagicMock())
        
        with patch.object(mock_google_genai, "types", mock_types):
            with patch.object(mock_google_genai, "Client"):
                client = GoogleClient(model="gemini-pro", api_key="test")
                messages = [
                    ChatMessage(
                        role="tool",
                        content="72F, Sunny",
                        tool_call_id="fc_get_weather",
                        name="get_weather"
                    ),
                ]
                converted = client._convert_messages(messages)
                assert len(converted) == 1

    def test_convert_messages_tool_response_extracts_name_from_id(self):
        mock_types = MagicMock()
        mock_types.Content = MagicMock(return_value=MagicMock())
        mock_types.Part = MagicMock()
        mock_types.FunctionResponse = MagicMock(return_value=MagicMock())
        
        with patch.object(mock_google_genai, "types", mock_types):
            with patch.object(mock_google_genai, "Client"):
                client = GoogleClient(model="gemini-pro", api_key="test")
                messages = [
                    ChatMessage(
                        role="tool",
                        content="Result",
                        tool_call_id="fc_search_docs"
                    ),
                ]
                converted = client._convert_messages(messages)
                assert len(converted) == 1

    def test_convert_tools(self):
        mock_types = MagicMock()
        mock_types.FunctionDeclaration = MagicMock(return_value=MagicMock())
        mock_types.Tool = MagicMock(return_value=MagicMock())
        
        with patch.object(mock_google_genai, "types", mock_types):
            with patch.object(mock_google_genai, "Client"):
                client = GoogleClient(model="gemini-pro", api_key="test")
                tools = [
                    {"name": "search", "description": "Search the web", "parameters": {}}
                ]
                converted = client._convert_tools(tools)
                assert converted is not None

    @pytest.mark.asyncio
    async def test_chat_with_mock(self):
        mock_response = MagicMock()
        mock_response.text = "Hello from Gemini!"
        mock_response.candidates = [MagicMock()]
        mock_response.candidates[0].content.parts = [MagicMock()]
        mock_response.candidates[0].content.parts[0].text = "Hello from Gemini!"
        mock_response.candidates[0].content.parts[0].function_call = None

        mock_client = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        with patch.object(mock_google_genai, "Client", return_value=mock_client):
            client = GoogleClient(model="gemini-pro", api_key="test")
            messages = [ChatMessage(role="user", content="Hi")]
            result = await client.chat(messages)

            assert result.content == "Hello from Gemini!"

    @pytest.mark.asyncio
    async def test_chat_with_tool_calls(self):
        mock_fc = MagicMock()
        mock_fc.name = "get_weather"
        mock_fc.args = {"city": "Tokyo"}

        mock_part = MagicMock()
        mock_part.text = None
        mock_part.function_call = mock_fc

        mock_response = MagicMock()
        mock_response.text = None
        mock_response.candidates = [MagicMock()]
        mock_response.candidates[0].content.parts = [mock_part]

        mock_client = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        with patch.object(mock_google_genai, "Client", return_value=mock_client):
            client = GoogleClient(model="gemini-pro", api_key="test")
            messages = [ChatMessage(role="user", content="Weather?")]
            result = await client.chat(messages)

            assert len(result.tool_calls) == 1
            assert result.tool_calls[0].name == "get_weather"
            assert result.tool_calls[0].arguments == {"city": "Tokyo"}


class TestCreateClient:
    def test_create_openai_client(self):
        with patch("openai.AsyncOpenAI") as MockAsyncOpenAI:
            MockAsyncOpenAI.return_value = MagicMock()
            client = create_client("gpt-4", provider="openai", api_key="test")
            assert isinstance(client, OpenAIClient)

    def test_create_google_client(self):
        mock_client = MagicMock()
        with patch.object(mock_google_genai, "Client", return_value=mock_client):
            client = create_client("gemini-pro", provider="google", api_key="test")
            assert isinstance(client, GoogleClient)

    def test_create_client_with_provider_prefix(self):
        with patch("openai.AsyncOpenAI") as MockAsyncOpenAI:
            MockAsyncOpenAI.return_value = MagicMock()
            client = create_client("anthropic:claude-3-opus", api_key="test")
            assert isinstance(client, OpenAIClient)

    def test_create_client_with_slash_prefix(self):
        mock_client = MagicMock()
        with patch.object(mock_google_genai, "Client", return_value=mock_client):
            client = create_client("google/gemini-pro", api_key="test")
            assert isinstance(client, GoogleClient)

    def test_create_client_auto_detect(self):
        with patch("openai.AsyncOpenAI") as MockAsyncOpenAI:
            MockAsyncOpenAI.return_value = MagicMock()
            client = create_client("claude-3-opus", api_key="test")
            assert isinstance(client, OpenAIClient)

        mock_client = MagicMock()
        with patch.object(mock_google_genai, "Client", return_value=mock_client):
            client = create_client("gemini-pro", api_key="test")
            assert isinstance(client, GoogleClient)


class TestLLMError:
    def test_llm_error_message(self):
        error = LLMError("API failed", provider="openai")
        assert str(error) == "API failed"
        assert error.provider == "openai"

    def test_llm_error_with_original(self):
        original = ValueError("Original error")
        error = LLMError("Wrapped", provider="google", original_error=original)
        assert error.original_error == original


class TestProviderUrlsIntegration:
    def test_provider_urls_contains_expected_providers(self):
        expected = ["openai", "anthropic", "google", "deepseek", "mistral", "groq"]
        for provider in expected:
            assert provider in PROVIDER_URLS, f"Missing {provider} in provider_urls.json"

    def test_provider_urls_has_base_url(self):
        for provider, config in PROVIDER_URLS.items():
            assert "base" in config, f"Missing base URL for {provider}"


class TestTruncateMessagesThinWrapper:
    def test_returns_unchanged_when_no_context(self):
        with patch("openai.AsyncOpenAI") as MockAsyncOpenAI:
            MockAsyncOpenAI.return_value = MagicMock()
            client = OpenAIClient(model="gpt-4", api_key="test")

        with patch("dashboard.lib.settings.models_dev_loader.truncate_messages_for_model", return_value=[{"role": "user", "content": "hi"}]):
            with patch("dashboard.lib.settings.models_dev_loader.get_context_limit", return_value=(0, 0)):
                msgs = [ChatMessage(role="user", content="hi")]
                result = client._truncate_messages(msgs)
        assert len(result) == 1
        assert result[0].content == "hi"

    def test_preserves_chat_message_fields_on_truncation(self):
        with patch("openai.AsyncOpenAI") as MockAsyncOpenAI:
            MockAsyncOpenAI.return_value = MagicMock()
            client = OpenAIClient(model="gpt-4", api_key="test", provider="openai")

        original = ChatMessage(
            role="assistant",
            content="long content that will be trimmed",
            tool_calls=[ToolCall(id="tc1", name="fn", arguments={"a": 1})],
            tool_call_id="tc1",
            name="fn",
            thought_signature="sig",
            images=["http://img.png"],
        )
        truncated_dicts = [{"role": "assistant", "content": "long content"}]

        with patch("dashboard.lib.settings.models_dev_loader.truncate_messages_for_model", return_value=truncated_dicts):
            result = client._truncate_messages([original])
        assert result[0].content == "long content"
        assert len(result[0].tool_calls) == 1
        assert result[0].tool_call_id == "tc1"
        assert result[0].name == "fn"
        assert result[0].thought_signature == "sig"
        assert result[0].images == ["http://img.png"]

    def test_returns_same_objects_when_no_change(self):
        with patch("openai.AsyncOpenAI") as MockAsyncOpenAI:
            MockAsyncOpenAI.return_value = MagicMock()
            client = OpenAIClient(model="gpt-4", api_key="test")

        msg = ChatMessage(role="user", content="short")
        with patch("dashboard.lib.settings.models_dev_loader.truncate_messages_for_model", return_value=[{"role": "user", "content": "short"}]):
            result = client._truncate_messages([msg])
        assert result[0] is msg

    def test_exception_returns_original_messages(self):
        with patch("openai.AsyncOpenAI") as MockAsyncOpenAI:
            MockAsyncOpenAI.return_value = MagicMock()
            client = OpenAIClient(model="gpt-4", api_key="test")

        msgs = [ChatMessage(role="user", content="hello")]
        with patch("dashboard.lib.settings.models_dev_loader.truncate_messages_for_model", side_effect=RuntimeError("boom")):
            result = client._truncate_messages(msgs)
        assert result == msgs


class TestSanitizeGeminiSchema:
    """``_sanitize_gemini_schema`` strips JSON-Schema fields that Gemini's
    Schema proto rejects (``additionalProperties``, ``$schema``, ``strict``,
    ``$ref``, ``oneOf``, ``definitions``, …) while preserving every key
    that lives inside ``properties`` (those are user-defined field names)
    and the literal entries of ``required``.
    """

    def test_strips_additional_properties(self):
        schema = {"type": "object", "additionalProperties": False, "properties": {"x": {"type": "string"}}}
        out = _sanitize_gemini_schema(schema)
        assert "additionalProperties" not in out
        assert out["type"] == "object"
        assert out["properties"] == {"x": {"type": "string"}}

    def test_strips_unknown_top_level_keys(self):
        schema = {
            "type": "object",
            "$schema": "http://json-schema.org/draft-07/schema#",
            "strict": True,
            "$ref": "#/definitions/Foo",
            "oneOf": [{"type": "string"}],
            "definitions": {"Foo": {"type": "string"}},
            "properties": {"x": {"type": "string"}},
        }
        out = _sanitize_gemini_schema(schema)
        for forbidden in ("$schema", "strict", "$ref", "oneOf", "definitions"):
            assert forbidden not in out
        assert out["type"] == "object"
        assert "properties" in out

    def test_preserves_property_keys_verbatim(self):
        # Property names must NOT be filtered by the allowlist — they are
        # user-defined field identifiers (could be anything like "additionalProperties"
        # as a field name) and their values are recursively sanitized.
        schema = {
            "type": "object",
            "properties": {
                "additionalProperties": {"type": "string"},  # property literally named that
                "strict": {"type": "boolean", "additionalProperties": False},
                "normal_field": {"type": "integer"},
            },
        }
        out = _sanitize_gemini_schema(schema)
        assert set(out["properties"].keys()) == {"additionalProperties", "strict", "normal_field"}
        # The value for "strict" is itself a schema — its additionalProperties must be stripped.
        assert "additionalProperties" not in out["properties"]["strict"]
        assert out["properties"]["strict"]["type"] == "boolean"

    def test_preserves_required_list_verbatim(self):
        schema = {
            "type": "object",
            "required": ["name", "age", "additionalProperties"],
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
                "additionalProperties": {"type": "string"},
            },
        }
        out = _sanitize_gemini_schema(schema)
        # required is a list of strings — preserved as-is (even if a string
        # happens to collide with a disallowed key name).
        assert out["required"] == ["name", "age", "additionalProperties"]

    def test_recurses_into_items(self):
        schema = {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"x": {"type": "string"}},
            },
        }
        out = _sanitize_gemini_schema(schema)
        assert "additionalProperties" not in out["items"]
        assert out["items"]["type"] == "object"

    def test_recurses_into_anyof(self):
        schema = {
            "anyOf": [
                {"type": "string", "strict": True},
                {"type": "object", "additionalProperties": False, "properties": {"x": {"type": "string"}}},
            ],
        }
        out = _sanitize_gemini_schema(schema)
        assert isinstance(out["anyOf"], list)
        assert "strict" not in out["anyOf"][0]
        assert "additionalProperties" not in out["anyOf"][1]

    def test_passthrough_for_scalar_inputs(self):
        assert _sanitize_gemini_schema("string") == "string"
        assert _sanitize_gemini_schema(42) == 42
        assert _sanitize_gemini_schema(True) is True
        assert _sanitize_gemini_schema(None) is None

    def test_list_of_scalars_preserved(self):
        # required: ["a", "b"] is the common case — list of strings.
        assert _sanitize_gemini_schema(["a", "b", "c"]) == ["a", "b", "c"]

    def test_nested_object_array_combo(self):
        # Realistic shape: object → array → object, with stray keys at every level.
        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "id": {"type": "string", "$ref": "ignored"},
                        },
                        "required": ["id"],
                    },
                },
            },
            "required": ["items"],
        }
        out = _sanitize_gemini_schema(schema)
        assert "additionalProperties" not in out
        item_schema = out["properties"]["items"]["items"]
        assert "additionalProperties" not in item_schema
        assert "$ref" not in item_schema["properties"]["id"]
        assert item_schema["required"] == ["id"]

    def test_allowed_keys_set_contains_core_schema_fields(self):
        # Smoke-check the allowlist contents to flag accidental removals.
        for k in ("type", "properties", "required", "items", "anyOf", "enum", "description"):
            assert k in _GEMINI_SCHEMA_ALLOWED_KEYS


class TestDetectEmbeddingProvider:
    """``_detect_embedding_provider_from_model`` routes bare model names to
    the right backend.  Crucially, sentence-transformers names no longer
    receive special-casing — they fall through to the ``ollama`` default
    (since ST support was removed from the codebase)."""

    def test_empty_model_defaults_to_ollama(self):
        assert _detect_embedding_provider_from_model("") == "ollama"

    def test_gemini_routes_to_google(self):
        assert _detect_embedding_provider_from_model("gemini-embedding-001") == "google"

    def test_vertex_in_name_routes_to_vertex(self):
        assert _detect_embedding_provider_from_model("vertex-gemini-embedding") == "google-vertex"

    def test_text_embedding_matches_google_branch_first(self):
        # Implementation order: "text-embedding" substring is checked in the
        # google branch before the openai-compatible branch.  This pins the
        # current behaviour so a refactor that reorders branches surfaces a
        # diff.
        assert _detect_embedding_provider_from_model("text-embedding-3-small") == "google"

    def test_gpt_prefix_routes_to_openai_compatible(self):
        assert _detect_embedding_provider_from_model("gpt-embedding") == "openai-compatible"

    def test_ollama_model_falls_through_to_ollama(self):
        assert _detect_embedding_provider_from_model("qwen3-embedding:0.6b") == "ollama"
        assert _detect_embedding_provider_from_model("nomic-embed-text") == "ollama"

    @pytest.mark.parametrize("model", ["all-MiniLM-L6-v2", "BAAI/bge-small-en-v1.5"])
    def test_legacy_sentence_transformer_names_are_rejected(self, model):
        with pytest.raises(ValueError, match="legacy sentence-transformer embedding models are no longer supported"):
            _detect_embedding_provider_from_model(model)


class TestCreateEmbeddingClient:
    """``create_embedding_client`` factory branches.  Tests bypass the
    singleton cache via ``shared=False`` so they don't pollute global state.
    """

    def test_ollama_branch_for_default_model(self):
        client = create_embedding_client(
            model="qwen3-embedding:0.6b",
            provider="ollama",
            shared=False,
        )
        assert isinstance(client, OllamaEmbeddingClient)
        assert client.model == "qwen3-embedding:0.6b"

    def test_ollama_branch_auto_detected(self):
        # No provider/ prefix and no explicit provider → defaults to ollama.
        client = create_embedding_client(model="qwen3-embedding:0.6b", shared=False)
        assert isinstance(client, OllamaEmbeddingClient)

    def test_openai_compatible_branch(self):
        # Use an "openai/" prefix so _CHAT_TO_EMBED_PROVIDER remaps
        # "openai" → "openai-compatible".  The factory only routes to
        # OpenAICompatibleEmbeddingClient when the remapped embed_provider
        # differs from the explicit model_provider (preventing a literal
        # "openai-compatible/" prefix from short-circuiting through here).
        client = create_embedding_client(
            model="openai/text-embedding-3-small",
            shared=False,
            base_url="http://localhost:9000",
            api_key="fake-key",
        )
        assert isinstance(client, OpenAICompatibleEmbeddingClient)
        # provider/ prefix must be stripped from the model name.
        assert client.model == "text-embedding-3-small"

    def test_google_branch_uses_gemini_client(self):
        # Need to patch google.genai.Client because GeminiEmbeddingClient
        # constructs one eagerly in __init__.
        with patch("dashboard.llm_client.GeminiEmbeddingClient") as MockGEC:
            MockGEC.return_value = MagicMock(spec=GeminiEmbeddingClient)
            client = create_embedding_client(
                model="google/gemini-embedding-001",
                shared=False,
                api_key="fake-key",
            )
            MockGEC.assert_called_once()
            # clean_model passed should have the provider prefix stripped.
            kwargs = MockGEC.call_args.kwargs
            assert kwargs["model"] == "gemini-embedding-001"
            assert kwargs["vertexai"] is False

    def test_google_vertex_branch_sets_vertexai_flag(self):
        with patch("dashboard.llm_client.GeminiEmbeddingClient") as MockGEC:
            MockGEC.return_value = MagicMock(spec=GeminiEmbeddingClient)
            create_embedding_client(
                model="google-vertex/gemini-embedding-001",
                shared=False,
                api_key="fake-key",
            )
            kwargs = MockGEC.call_args.kwargs
            assert kwargs["vertexai"] is True
            assert kwargs["model"] == "gemini-embedding-001"

    def test_unknown_provider_falls_back_to_ollama(self):
        client = create_embedding_client(
            model="some-model",
            provider="totally-unknown-provider",
            shared=False,
        )
        assert isinstance(client, OllamaEmbeddingClient)

    @pytest.mark.parametrize("provider", ["sentence-transformer", "sentence-transformers", "sentence_transformers"])
    def test_sentence_transformers_provider_is_rejected(self, provider):
        with pytest.raises(ValueError, match="sentence-transformers embeddings are no longer supported"):
            create_embedding_client(
                model="all-MiniLM-L6-v2",
                provider=provider,
                shared=False,
            )

    @pytest.mark.parametrize("model", [
        "sentence-transformer/all-MiniLM-L6-v2",
        "sentence-transformers/all-MiniLM-L6-v2",
        "sentence_transformers/all-MiniLM-L6-v2",
    ])
    def test_sentence_transformers_model_prefix_is_rejected(self, model):
        with pytest.raises(ValueError, match="sentence-transformers embeddings are no longer supported"):
            create_embedding_client(model=model, shared=False)

    @pytest.mark.parametrize("model", ["all-MiniLM-L6-v2", "BAAI/bge-small-en-v1.5"])
    def test_legacy_sentence_transformer_model_ids_are_rejected(self, model):
        with pytest.raises(ValueError, match="legacy sentence-transformer embedding models are no longer supported"):
            create_embedding_client(model=model, shared=False)

    def test_shared_cache_returns_same_instance(self):
        # The factory caches by (provider, model, dimension); two shared
        # lookups with identical keys must return the same object.
        from dashboard.llm_client import _embedding_cache
        _embedding_cache.clear()
        c1 = create_embedding_client(model="qwen3-embedding:0.6b", provider="ollama", dimension=512)
        c2 = create_embedding_client(model="qwen3-embedding:0.6b", provider="ollama", dimension=512)
        assert c1 is c2

    def test_shared_false_returns_new_instance(self):
        c1 = create_embedding_client(model="qwen3-embedding:0.6b", provider="ollama", shared=False)
        c2 = create_embedding_client(model="qwen3-embedding:0.6b", provider="ollama", shared=False)
        assert c1 is not c2

    def test_sentence_transformers_class_no_longer_exists(self):
        # Compile-time assertion: the ST embedding client class was removed.
        import dashboard.llm_client as llm_client_mod
        assert not hasattr(llm_client_mod, "SentenceTransformersEmbeddingClient")
