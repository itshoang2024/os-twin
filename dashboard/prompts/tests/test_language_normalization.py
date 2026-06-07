import pytest
from unittest.mock import Mock
from igotapi.prompts.registry import PromptRegistry
from igotapi.prompts.providers.base import BasePromptProvider
from igotapi.prompts.exceptions import PromptNotFoundError

class MockProvider(BasePromptProvider):
    def __init__(self):
        self.data = {}
    
    def load(self, key: str, lang: str):
        return self.data.get(lang, {}).get(key)
    
    def save(self, key: str, lang: str, template: str):
        if lang not in self.data:
            self.data[lang] = {}
        self.data[lang][key] = template

    def exists(self, key: str, lang: str):
        return key in self.data.get(lang, {})

    def list_languages(self):
        return list(self.data.keys())

    def list_keys(self, lang: str):
        return list(self.data.get(lang, {}).keys())

def test_language_normalization():
    provider = MockProvider()
    registry = PromptRegistry(provider)
    
    registry.set_prompt("greeting", "en", "Hello")
    registry.set_prompt("greeting", "vi", "Xin chào")
    
    assert registry.get_prompt("greeting", "en") == "Hello" # Test English variants
    assert registry.get_prompt("greeting", "eng") == "Hello"
    assert registry.get_prompt("greeting", "English") == "Hello"
    assert registry.get_prompt("greeting", "english") == "Hello"
    assert registry.get_prompt("greeting", "england") == "Hello"
    assert registry.get_prompt("greeting", "England") == "Hello"
    
    assert registry.get_prompt("greeting", "vi") == "Xin chào" # Test Vietnamese variants
    assert registry.get_prompt("greeting", "vn") == "Xin chào"
    assert registry.get_prompt("greeting", "Vietnamese") == "Xin chào"
    assert registry.get_prompt("greeting", "Vietnam") == "Xin chào"
    assert registry.get_prompt("greeting", "Tiếng Việt") == "Xin chào"
    assert registry.get_prompt("greeting", "tiếng việt") == "Xin chào"

def test_language_fallback():
    provider = MockProvider()
    registry = PromptRegistry(provider)
    
    registry.set_prompt("greeting", "en", "Hello")
    
    assert registry.get_prompt("greeting", "fr") == "Hello" # Test fallback to "en" for unknown language
    assert registry.get_prompt("greeting", "unknown") == "Hello"

def test_language_fallback_failure():
    provider = MockProvider()
    registry = PromptRegistry(provider)
    
    # No "en" prompt
    registry.set_prompt("greeting", "vi", "Xin chào")
    
    with pytest.raises(PromptNotFoundError):
        registry.get_prompt("greeting", "fr")

def test_language_normalization_with_whitespace():
    provider = MockProvider()
    registry = PromptRegistry(provider)
    
    registry.set_prompt("greeting", "en", "Hello")
    assert registry.get_prompt("greeting", "  en  ") == "Hello"
    assert registry.get_prompt("greeting", "ENGLISH  ") == "Hello"
