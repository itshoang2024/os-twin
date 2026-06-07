import pytest
import os
import yaml
from igotapi.prompts.providers.memory_provider import MemoryPromptProvider
from igotapi.prompts.providers.file_provider import FilePromptProvider

def test_memory_provider():
    provider = MemoryPromptProvider()
    provider.save("test.key", "en", "English Template")
    provider.save("test.key", "vi", "Vietnamese Template")
    
    assert provider.load("test.key", "en") == "English Template"
    assert provider.load("test.key", "vi") == "Vietnamese Template"
    assert provider.exists("test.key", "en") is True
    assert provider.exists("test.key", "fr") is False
    assert set(provider.list_languages()) == {"en", "vi"}
    assert provider.list_keys("en") == ["test.key"]

def test_file_provider(tmp_path):
    locales_dir = tmp_path / "locales"
    locales_dir.mkdir()
    
    en_content = {
        "namespace": {
            "key": "English Template"
        }
    }
    with open(locales_dir / "en.yaml", "w") as f:
        yaml.dump(en_content, f)
        
    provider = FilePromptProvider(str(locales_dir))
    
    assert provider.load("namespace.key", "en") == "English Template"
    assert provider.load("non.existent", "en") is None
    assert provider.load("namespace.key", "vi") is None
    
    assert provider.list_languages() == ["en"]
    assert provider.list_keys("en") == ["namespace.key"]

def test_file_provider_save_memory_only(tmp_path):
    locales_dir = tmp_path / "locales"
    locales_dir.mkdir()
    
    provider = FilePromptProvider(str(locales_dir))
    provider.save("new.key", "en", "New Template")
    
    assert provider.load("new.key", "en") == "New Template"
    # Verify it's not written to file (as per current implementation)
    assert not os.path.exists(locales_dir / "en.yaml")
