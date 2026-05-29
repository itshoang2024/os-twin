"""Tests for Ollama error handling through the new MemoryLLM stack.

The old OllamaController and its litellm dependency are gone. Ollama errors
are now handled by dashboard.llm_client.OllamaClient with retry/timeout via
BaseLLMWrapper._complete(). This file verifies the new error paths.

Embedding errors go through CentralizedEmbeddingFunction →
llm_client.create_embedding_client() → OllamaClient.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from dashboard.agentic_memory.memory_llm import MemoryLLM
from dashboard.llm_wrapper import BaseLLMWrapper


class TestOllamaConnectionErrorThroughMemoryLLM:
    @patch("dashboard.llm_wrapper.run_sync")
    def test_connection_error_returns_empty_string(self, mock_run_sync):
        mock_run_sync.side_effect = ConnectionError("Connection refused")

        llm = MemoryLLM(model="llama3.2", provider="ollama", api_key="unused")
        with patch.object(llm, "is_available", return_value=True):
            result = llm.get_completion("Hello")
        assert result == ""


class TestOllamaEmbeddingConnectionError:
    """Test Ollama embedding errors through CentralizedEmbeddingFunction.

    CentralizedEmbeddingFunction delegates to llm_client.create_embedding_client(),
    which creates an OllamaClient for provider="ollama". We mock the embedding
    client to simulate Ollama server errors.
    """

    def test_ollama_embedding_connection_error(self):
        """Connection refused when Ollama server is down."""
        from dashboard.agentic_memory.retrievers import CentralizedEmbeddingFunction

        embedder = CentralizedEmbeddingFunction(model_name="harrier", embedding_backend="ollama")

        # Mock the client to raise ConnectionError
        mock_client = MagicMock()
        mock_client.embed.side_effect = ConnectionError("Connection refused")
        embedder._client = mock_client

        with pytest.raises(ConnectionError, match="Connection refused"):
            embedder(["test document"])

    def test_ollama_embedding_model_not_found(self):
        """Model not found error from Ollama."""
        from dashboard.agentic_memory.retrievers import CentralizedEmbeddingFunction

        embedder = CentralizedEmbeddingFunction(model_name="harrier", embedding_backend="ollama")

        # Mock the client to raise RuntimeError (model not found)
        mock_client = MagicMock()
        mock_client.embed.side_effect = RuntimeError("Model 'harrier' not found")
        embedder._client = mock_client

        with pytest.raises(RuntimeError, match="Model 'harrier' not found"):
            embedder(["test document"])
