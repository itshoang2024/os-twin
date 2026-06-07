import pytest
from igotapi.prompts.formatter import PromptFormatter
from igotapi.prompts.exceptions import PromptValidationError

def test_format_success():
    formatter = PromptFormatter()
    template = "Hello {name}, welcome to {place}!"
    result = formatter.format(template, name="Alice", place="Wonderland")
    assert result == "Hello Alice, welcome to Wonderland!"

def test_format_missing_arg():
    formatter = PromptFormatter()
    template = "Hello {name}!"
    with pytest.raises(PromptValidationError) as excinfo:
        formatter.format(template)
    assert "Missing required argument: name" in str(excinfo.value)

def test_extract_placeholders():
    formatter = PromptFormatter()
    template = "Hello {name}, welcome to {place}! {extra}"
    placeholders = formatter.extract_placeholders(template)
    assert placeholders == {"name", "place", "extra"}

def test_extract_placeholders_with_escaped():
    formatter = PromptFormatter()
    template = "Hello {name}, here is a literal {{brace}} and {another}."
    placeholders = formatter.extract_placeholders(template)
    assert placeholders == {"name", "another"}

def test_validate_args():
    formatter = PromptFormatter()
    template = "Hello {name}, welcome to {place}!"
    missing = formatter.validate_args(template, {"name": "Alice"})
    assert missing == {"place"}
    
    missing = formatter.validate_args(template, {"name": "Alice", "place": "Wonderland"})
    assert missing == set()
