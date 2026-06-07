import os
import re
import yaml
import pytest
from typing import Dict, Set, Any
from igotapi.prompts.providers.file_provider import FilePromptProvider

def get_locales_dir() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "locales"))  # Path to locales directory

@pytest.fixture
def locales_dir() -> str:
    return get_locales_dir()

@pytest.fixture
def provider(locales_dir: str) -> FilePromptProvider:
    return FilePromptProvider(locales_dir)

def extract_placeholders(template: str) -> Set[str]:
    """
    Extracts placeholders like {name} but ignores escaped {{ braces }}.
    """
    if not isinstance(template, str):
        return set()
    
    # Replace escaped {{ and }} to avoid matching them
    temp_template = template.replace("{{", "<<DBL_OPEN>>").replace("}}", "<<DBL_CLOSE>>")  # Handle escaped braces
    
    # Find all {placeholder}
    placeholders = re.findall(r"\{(\w+)\}", temp_template)  # Extract placeholder names
    return set(placeholders)

def get_all_keys(data: Dict[str, Any], prefix: str = "") -> Set[str]:
    """Recursively get all keys in a nested dictionary."""
    keys = set()
    for k, v in data.items():
        full_key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            keys.update(get_all_keys(v, full_key))  # Recurse into nested dict
        else:
            keys.add(full_key)  # Add leaf key
    return keys

def test_locales_exist(locales_dir: str):
    assert os.path.exists(os.path.join(locales_dir, "en.yaml")), "en.yaml missing"
    assert os.path.exists(os.path.join(locales_dir, "vi.yaml")), "vi.yaml missing"

def test_prompt_keys_consistency(provider: FilePromptProvider):
    en_data = provider._load_file("en")
    vi_data = provider._load_file("vi")
    
    en_keys = get_all_keys(en_data)
    vi_keys = get_all_keys(vi_data)
    
    missing_in_vi = en_keys - vi_keys
    extra_in_vi = vi_keys - en_keys
    
    assert not missing_in_vi, f"Keys present in en.yaml but missing in vi.yaml: {missing_in_vi}"
    assert not extra_in_vi, f"Keys present in vi.yaml but missing in en.yaml: {extra_in_vi}"

def test_prompt_placeholders_consistency(provider: FilePromptProvider):
    en_data = provider._load_file("en")
    en_keys = get_all_keys(en_data)
    
    for key in en_keys:
        en_val = provider.load(key, "en")
        vi_val = provider.load(key, "vi")
        
        # We already checked key existence in test_prompt_keys_consistency
        if vi_val is None:
            continue
            
        en_placeholders = extract_placeholders(en_val)
        vi_placeholders = extract_placeholders(vi_val)
        
        assert en_placeholders == vi_placeholders, \
            f"Placeholder mismatch for key '{key}': en={en_placeholders}, vi={vi_placeholders}"

def test_no_empty_prompts(provider: FilePromptProvider):
    for lang in ["en", "vi"]:
        data = provider._load_file(lang)
        keys = get_all_keys(data)
        for key in keys:
            val = provider.load(key, lang)
            assert val and val.strip(), f"Prompt '{key}' in '{lang}' is empty or whitespace only"

@pytest.mark.parametrize("key", [
    "orchestrator.query_executor.plan_query",
    "orchestrator.query_executor.plan_assistant",
    "orchestrator.query_executor.user_plan",
    "orchestrator.query_executor.system_aggregate",
    "orchestrator.query_executor.assistant_aggregate",
    "orchestrator.kg_extraction.steps_json",
    "orchestrator.kg_extraction.example_json",
    "orchestrator.kg_extraction.output_format_template",
    "orchestrator.kg_extraction.domain_format",
    "orchestrator.kg_extraction.extraction_steps",
    "orchestrator.kg_extraction.triplet_extract_tmpl",
    "orchestrator.kg_extraction.goal",
    "orchestrator.kg_extraction.system_role"
])
def test_specific_prompts_format(provider: FilePromptProvider, key: str):
    """Ensure specific prompts contain expected markers or structure."""
    for lang in ["en", "vi"]:
        val = provider.load(key, lang)
        assert val is not None, f"Key '{key}' missing for lang '{lang}'"
        
        if "json" in key.lower() or "template" in key.lower():
            # Check for common JSON-like or template markers if applicable
            if "example_json" in key:
                assert "{" in val and "}" in val, f"'{key}' in '{lang}' should look like JSON"
            if "output_format_template" in key:
                # Standard format should have entities and relationships
                assert "entities" in val.lower(), f"'{key}' in '{lang}' missing 'entities'"
                assert "relationships" in val.lower(), f"'{key}' in '{lang}' missing 'relationships'"

def test_escaped_braces_integrity(provider: FilePromptProvider):
    """
    Check if double braces are consistent. If EN uses literal braces {{ }}, 
    VI should likely also use them to maintain JSON/structure integrity.
    """
    en_data = provider._load_file("en")
    en_keys = get_all_keys(en_data)
    
    for key in en_keys:
        en_val = provider.load(key, "en")
        vi_val = provider.load(key, "vi")
        
        if vi_val is None:
            continue
            
        en_escaped_open = en_val.count("{{")
        en_escaped_close = en_val.count("}}")
        vi_escaped_open = vi_val.count("{{")
        vi_escaped_close = vi_val.count("}}")
        
        assert en_escaped_open == vi_escaped_open, \
            f"Escaped open brace '{{{{' count mismatch for '{key}': en={en_escaped_open}, vi={vi_escaped_open}"
        assert en_escaped_close == vi_escaped_close, \
            f"Escaped close brace '}}}}' count mismatch for '{key}': en={en_escaped_close}, vi={vi_escaped_close}"
