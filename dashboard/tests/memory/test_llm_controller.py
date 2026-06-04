"""Unit tests for memory_llm.MemoryLLM (replaces old llm_controller tests).

These tests verify the MemoryLLM class which is the replacement for the
old llm_controller.py that had 6 separate backend classes.
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from dashboard.llm_wrapper import BaseLLMWrapper
from dashboard.agentic_memory.memory_llm import MemoryLLM


class TestBaseLLMWrapperEmptyResponse:
    def test_generate_empty_response_matches_schema(self):
        response_format = {
            "json_schema": {
                "schema": {
                    "properties": {
                        "keywords": {"type": "array"},
                        "context": {"type": "string"},
                        "score": {"type": "number"},
                        "enabled": {"type": "boolean"},
                    }
                }
            }
        }
        result = BaseLLMWrapper._generate_empty_response(response_format)
        assert result == {
            "keywords": [],
            "context": "",
            "score": 0,
            "enabled": False,
        }

    def test_generate_empty_response_no_json_schema(self):
        result = BaseLLMWrapper._generate_empty_response({})
        assert result == {}

    def test_generate_empty_value_all_types(self):
        assert BaseLLMWrapper._generate_empty_value("array") == []
        assert BaseLLMWrapper._generate_empty_value("string") == ""
        assert BaseLLMWrapper._generate_empty_value("object") == {}
        assert BaseLLMWrapper._generate_empty_value("number") == 0
        assert BaseLLMWrapper._generate_empty_value("integer") == 0
        assert BaseLLMWrapper._generate_empty_value("boolean") is False
        assert BaseLLMWrapper._generate_empty_value("unknown") is None


class TestMemoryLLMInit:
    def test_init_with_explicit_params(self):
        llm = MemoryLLM(model="gemini-pro", provider="google", api_key="test-key")
        assert llm.model == "gemini-pro"
        assert llm.provider == "google"
        assert llm._explicit_key == "test-key"

    @patch.dict("os.environ", {"MEMORY_LLM_MODEL": "gpt-4", "MEMORY_LLM_BACKEND": "openai"})
    def test_init_resolves_from_env(self):
        with patch("dashboard.agentic_memory.memory_llm.MemoryLLM._resolve_model", return_value="gpt-4"):
            with patch("dashboard.agentic_memory.memory_llm.MemoryLLM._resolve_provider", return_value="openai"):
                llm = MemoryLLM()
                assert llm.model == "gpt-4"
                assert llm.provider == "openai"

    def test_is_available_no_model(self):
        llm = MemoryLLM(model="", api_key="test-key")
        assert not llm.is_available()

    def test_is_available_with_model_and_key(self):
        llm = MemoryLLM(model="gemini-pro", api_key="test-key")
        assert llm.is_available()


class TestMemoryLLMGetCompletion:
    def test_get_completion_unavailable_returns_empty(self):
        llm = MemoryLLM(model="", api_key="")
        result = llm.get_completion("test prompt")
        assert result == ""

    def test_get_completion_unavailable_with_format_returns_empty_json(self):
        llm = MemoryLLM(model="", api_key="")
        response_format = {"json_schema": {"schema": {"properties": {"keywords": {"type": "array"}}}}}
        result = llm.get_completion("test prompt", response_format=response_format)
        parsed = json.loads(result)
        assert parsed == {"keywords": []}

    @patch("dashboard.llm_wrapper.run_sync")
    def test_get_completion_available_returns_text(self, mock_run_sync):
        mock_response = MagicMock()
        mock_response.content = "Hello from LLM"
        mock_run_sync.return_value = mock_response

        llm = MemoryLLM(model="gemini-pro", provider="google", api_key="test-key")
        with patch.object(llm, "is_available", return_value=True):
            result = llm.get_completion("test prompt")
        assert result == "Hello from LLM"

    @patch("dashboard.llm_wrapper.run_sync")
    def test_get_completion_timeout_returns_empty(self, mock_run_sync):
        import asyncio

        mock_run_sync.side_effect = asyncio.TimeoutError()

        llm = MemoryLLM(model="gemini-pro", provider="google", api_key="test-key")
        with patch.object(llm, "is_available", return_value=True):
            result = llm.get_completion("test prompt")
        assert result == ""

    @patch("dashboard.llm_wrapper.run_sync")
    def test_get_completion_with_format_and_schema(self, mock_run_sync):
        mock_response = MagicMock()
        mock_response.content = '{"keywords": ["memory", "test"]}'
        mock_run_sync.return_value = mock_response

        llm = MemoryLLM(model="gemini-pro", provider="google", api_key="test-key")
        with patch.object(llm, "is_available", return_value=True):
            response_format = {
                "json_schema": {"schema": {"properties": {"keywords": {"type": "array", "items": {"type": "string"}}}}}
            }
            result = llm.get_completion("Extract keywords", response_format=response_format)
        parsed = json.loads(result)
        assert parsed["keywords"] == ["memory", "test"]


class TestExtractJson:
    def test_extract_json_plain(self):
        assert BaseLLMWrapper._extract_json('{"a": 1}') == {"a": 1}

    def test_extract_json_fenced(self):
        assert BaseLLMWrapper._extract_json('```json\n{"a": 1}\n```') == {"a": 1}

    def test_extract_json_embedded(self):
        result = BaseLLMWrapper._extract_json('Here is the data: {"a": 1} done')
        assert result == {"a": 1}

    def test_extract_json_array(self):
        assert BaseLLMWrapper._extract_json("[1, 2, 3]") == [1, 2, 3]

    def test_extract_json_invalid(self):
        assert BaseLLMWrapper._extract_json("no json here") is None
