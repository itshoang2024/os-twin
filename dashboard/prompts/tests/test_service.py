import pytest
from unittest.mock import Mock
from igotapi.prompts.service import PromptService
from igotapi.prompts.exceptions import PromptNotFoundError

@pytest.fixture
def mock_provider():
    provider = Mock()
    def load_side_effect(key, lang):
        data = {
            "en": {
                "test.key": "English {name}",
                "only.en": "Only English {name}"
            },
            "vi": {
                "test.key": "Vietnamese {name}"
            }
        }
        return data.get(lang, {}).get(key)
    provider.load.side_effect = load_side_effect
    return provider

def test_service_get_success(mock_provider):
    service = PromptService(mock_provider)
    result = service.get("test.key", lang="en", name="Alice")
    assert result == "English Alice"
    
    result = service.get("test.key", lang="vi", name="Alice")
    assert result == "Vietnamese Alice"

def test_service_fallback(mock_provider):
    service = PromptService(mock_provider, default_language="en")
    # Fetching 'only.en' in 'vi' should fallback to 'en'
    result = service.get("only.en", lang="vi", name="Alice")
    assert result == "Only English Alice"

def test_service_not_found(mock_provider):
    service = PromptService(mock_provider)
    with pytest.raises(PromptNotFoundError):
        service.get("non.existent", lang="en")

def test_service_supports_language(mock_provider):
    mock_provider.list_languages.return_value = ["en", "vi"]
    service = PromptService(mock_provider)
    assert service.supports_language("en") is True
    assert service.supports_language("fr") is False
