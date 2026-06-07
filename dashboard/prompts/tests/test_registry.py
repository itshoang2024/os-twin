import pytest
from unittest.mock import Mock
from igotapi.prompts.registry import PromptRegistry
from igotapi.prompts.exceptions import PromptNotFoundError

def test_registry_get_prompt_caching():
    mock_provider = Mock()
    mock_provider.load.return_value = "Template"
    
    registry = PromptRegistry(mock_provider)
    
    # First call - loads from provider
    assert registry.get_prompt("key", "en") == "Template"
    mock_provider.load.assert_called_once_with("key", "en")
    
    # Second call - should use cache
    assert registry.get_prompt("key", "en") == "Template"
    assert mock_provider.load.call_count == 1

def test_registry_get_prompt_not_found():
    mock_provider = Mock()
    mock_provider.load.return_value = None
    
    registry = PromptRegistry(mock_provider)
    with pytest.raises(PromptNotFoundError):
        registry.get_prompt("missing", "en")

def test_registry_register_namespace():
    mock_provider = Mock()
    registry = PromptRegistry(mock_provider)
    
    prompts = {
        "key1": {"en": "EN1", "vi": "VI1"},
        "key2": {"en": "EN2"}
    }
    
    registry.register_namespace("test", prompts)
    
    assert mock_provider.save.call_count == 3
    mock_provider.save.assert_any_call("test.key1", "en", "EN1")
    mock_provider.save.assert_any_call("test.key1", "vi", "VI1")
    mock_provider.save.assert_any_call("test.key2", "en", "EN2")
