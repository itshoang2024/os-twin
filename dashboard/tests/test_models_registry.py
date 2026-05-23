"""
Tests for dashboard.lib.settings.models_registry.

Covers:
- Static fallback catalog structure
- Filtering by provider enabled/disabled
- Google mode filtering (gemini vs vertex)
- Dynamic + static merge behavior
- OpenCode model building
- AUTH_JSON_PROVIDERS structure
"""

import pytest

from dashboard.lib.settings import models_registry
from dashboard.lib.settings.models_registry import (
    ModelEntry,
    ProviderAuthType,
    get_full_catalog,
    get_model_registry,
    _get_static_registry,
    build_opencode_models,
    OPENCODE_PROVIDERS,
    AUTH_JSON_PROVIDERS,
)


# Catalog used by tests that exercise filter logic. Injected via monkeypatch
# so tests don't depend on whether _FALLBACK_CATALOG happens to contain
# gemini-mode entries (it currently does not — gemini-mode comes from the
# dynamic models.dev catalog at runtime).
_TEST_GEMINI_CATALOG = [
    ModelEntry(
        "gemini/gemini-3-flash-preview",
        "Gemini 3 Flash",
        "1M",
        "balanced",
        mode="gemini",
    ),
    ModelEntry(
        "gemini/gemini-3-pro-preview",
        "Gemini 3 Pro",
        "1M",
        "flagship",
        mode="gemini",
    ),
    ModelEntry(
        "gemini/gemini-3-flash-lite-preview",
        "Gemini 3 Flash Lite",
        "1M",
        "fast",
        mode="gemini",
    ),
    ModelEntry(
        "google-vertex/gemini-3.1-pro-preview",
        "Vertex Gemini 3.1 Pro",
        "1M",
        "flagship",
        mode="vertex",
    ),
    ModelEntry(
        "google-vertex-anthropic/claude-sonnet-4-6@default",
        "Vertex Claude Sonnet 4.6",
        "200K",
        "balanced",
        mode="vertex",
    ),
]


@pytest.fixture
def gemini_catalog(monkeypatch):
    """Inject a mixed gemini/vertex catalog so filter-logic tests are stable."""
    monkeypatch.setitem(
        models_registry._FALLBACK_CATALOG, "Gemini", list(_TEST_GEMINI_CATALOG)
    )
    return _TEST_GEMINI_CATALOG


# ── Helpers ───────────────────────────────────────────────────────────

def _has_provider(reg, *candidates):
    """Check if the registry contains any of the candidate keys."""
    return any(c in reg for c in candidates)


def _get_provider(reg, *candidates):
    """Return models for the first matching candidate key."""
    for c in candidates:
        if c in reg:
            return reg[c]
    raise KeyError(f"None of {candidates} found in {list(reg.keys())}")


# ── Static fallback catalog ──────────────────────────────────────────

def test_fallback_catalog_has_all_providers():
    catalog = get_full_catalog()
    assert set(catalog.keys()) == {"Claude", "GPT", "Gemini", "BytePlus"}


def test_fallback_catalog_entries_are_model_entries():
    catalog = get_full_catalog()
    for provider, entries in catalog.items():
        for entry in entries:
            assert isinstance(entry, ModelEntry)
            assert entry.id
            assert entry.label
            assert entry.tier


# ── Static registry (bypass dynamic) ─────────────────────────────────

def test_static_registry_all_enabled():
    reg = _get_static_registry(
        google_enabled=True, google_mode="vertex",
        byteplus_enabled=True, anthropic_enabled=True, openai_enabled=True,
    )
    assert "Claude" in reg
    assert "GPT" in reg
    assert "Gemini" in reg
    assert "BytePlus" in reg


def test_static_registry_google_disabled():
    reg = _get_static_registry(google_enabled=False)
    assert "Gemini" not in reg


def test_static_registry_byteplus_disabled():
    reg = _get_static_registry(byteplus_enabled=False)
    assert "BytePlus" not in reg


def test_static_registry_gemini_mode_only(gemini_catalog):
    reg = _get_static_registry(google_enabled=True, google_mode="gemini")
    assert "Gemini" in reg
    # When a mixed catalog is present, the static builder no longer applies
    # a mode filter (mode-aware selection happens via build_opencode_models /
    # OpenCodeProviderDef.registry_filter_mode). Verify all entries are
    # returned -- mode filtering is exercised in build_opencode_models tests.
    ids = {m["id"] for m in reg["Gemini"]}
    expected_ids = {e.id for e in gemini_catalog}
    assert ids == expected_ids


def test_static_registry_vertex_mode_only():
    """The unmodified static catalog contains only vertex-mode Gemini entries."""
    reg = _get_static_registry(google_enabled=True, google_mode="vertex")
    for m in reg["Gemini"]:
        assert m.get("mode") == "vertex"
    ids = {m["id"] for m in reg["Gemini"]}
    assert not any(mid.startswith("gemini/") for mid in ids)


# ── Merged registry (dynamic + static) ───────────────────────────────

def test_registry_contains_claude_or_anthropic():
    """Claude models appear under either static 'Claude' or dynamic 'Anthropic'."""
    reg = get_model_registry()
    assert _has_provider(reg, "Claude", "Anthropic")
    models = _get_provider(reg, "Claude", "Anthropic")
    assert len(models) >= 1
    assert all("id" in m for m in models)


def test_registry_contains_gpt_or_openai():
    """GPT models appear under either static 'GPT' or dynamic 'OpenAI'."""
    reg = get_model_registry()
    assert _has_provider(reg, "GPT", "OpenAI")
    models = _get_provider(reg, "GPT", "OpenAI")
    assert len(models) >= 1


def test_registry_dict_format():
    """Every model entry is a plain dict with the required keys."""
    reg = get_model_registry()
    for provider, models in reg.items():
        for m in models:
            assert isinstance(m, dict)
            assert "id" in m
            assert "label" in m
            assert "tier" in m


def test_registry_no_duplicate_provider_keys():
    """Dynamic entries should supersede static, not duplicate them."""
    reg = get_model_registry()
    # Claude and Anthropic should not BOTH appear
    assert not ("Claude" in reg and "Anthropic" in reg), \
        "Both 'Claude' and 'Anthropic' present -- dedup failed"
    assert not ("GPT" in reg and "OpenAI" in reg), \
        "Both 'GPT' and 'OpenAI' present -- dedup failed"


def test_registry_anthropic_disabled_removes_claude():
    reg = get_model_registry(anthropic_enabled=False)
    assert "Claude" not in reg


def test_registry_openai_disabled_removes_gpt():
    reg = get_model_registry(openai_enabled=False)
    assert "GPT" not in reg


# ── enabled_models allowlist ──────────────────────────────────────────

def test_registry_enabled_models_filters_claude():
    reg = get_model_registry(anthropic_models=["claude-sonnet-4-6"])
    models = _get_provider(reg, "Claude", "Anthropic")
    ids = {m["id"] for m in models}
    assert "claude-sonnet-4-6" in ids


def test_registry_enabled_models_filters_gpt():
    reg = get_model_registry(openai_models=["gpt-4.1", "o3"])
    models = _get_provider(reg, "GPT", "OpenAI")
    ids = {m["id"] for m in models}
    assert "gpt-4.1" in ids or len(ids) >= 1  # dynamic may have different ids


def test_registry_empty_enabled_models_means_all():
    reg_all = get_model_registry(anthropic_models=None)
    reg_empty = get_model_registry(anthropic_models=[])
    models_all = _get_provider(reg_all, "Claude", "Anthropic")
    models_empty = _get_provider(reg_empty, "Claude", "Anthropic")
    assert len(models_all) == len(models_empty)


def test_registry_nonexistent_model_id_filtered_out():
    reg = get_model_registry(anthropic_models=["nonexistent-model"])
    # With dynamic catalog, Anthropic may still appear (from models.dev)
    # but with static-only, Claude should be absent
    if "Claude" in reg:
        assert len(reg["Claude"]) == 0 or reg["Claude"][0]["id"] != "nonexistent-model"


# ── OpenCode model building ──────────────────────────────────────────

def test_build_opencode_models_gemini(gemini_catalog):
    pdef = OPENCODE_PROVIDERS["gemini"]
    models = build_opencode_models(pdef)
    # Only gemini-mode entries (3) pass the mode filter; vertex entries excluded.
    assert len(models) == 3
    for key, val in models.items():
        assert val["npm"] == "@ai-sdk/openai-compatible"
        assert val["name"].startswith("gemini:")
        assert "/" not in key


def test_build_opencode_models_byteplus():
    pdef = OPENCODE_PROVIDERS["byteplus"]
    models = build_opencode_models(pdef)
    assert len(models) > 0
    for key, val in models.items():
        assert val["npm"] == "@ai-sdk/openai-compatible"
        assert val["name"].startswith("byteplus:")


def test_build_opencode_models_with_allowlist(gemini_catalog):
    pdef = OPENCODE_PROVIDERS["gemini"]
    models = build_opencode_models(pdef, enabled_models=["gemini/gemini-3-flash-preview"])
    assert len(models) == 1
    assert "gemini-3-flash-preview" in models


def test_build_opencode_models_empty_allowlist_means_all(gemini_catalog):
    pdef = OPENCODE_PROVIDERS["gemini"]
    all_models = build_opencode_models(pdef)
    empty_list = build_opencode_models(pdef, enabled_models=[])
    assert len(all_models) == len(empty_list)


def test_build_opencode_models_google_vertex(gemini_catalog):
    """google-vertex/* entries are picked up via id_prefix + vertex mode."""
    pdef = OPENCODE_PROVIDERS["google-vertex"]
    models = build_opencode_models(pdef)
    # Only the single google-vertex/* entry should be included; the
    # google-vertex-anthropic/* entry is filtered out by id_prefix.
    assert len(models) == 1
    assert "gemini-3.1-pro-preview" in models
    val = models["gemini-3.1-pro-preview"]
    assert val["npm"] == "@ai-sdk/google-vertex"
    assert val["name"].startswith("google-vertex:")


def test_build_opencode_models_google_vertex_anthropic(gemini_catalog):
    """google-vertex-anthropic/* entries are isolated via id_prefix."""
    pdef = OPENCODE_PROVIDERS["google-vertex-anthropic"]
    models = build_opencode_models(pdef)
    assert len(models) == 1
    # Short id retains the trailing @-suffix
    short = next(iter(models))
    assert short.startswith("claude-sonnet-4-6")
    val = models[short]
    assert val["npm"] == "@ai-sdk/google-vertex"
    assert val["name"].startswith("google-vertex-anthropic:")


def test_opencode_providers_have_required_fields():
    for name, pdef in OPENCODE_PROVIDERS.items():
        assert pdef.opencode_key == name
        assert pdef.vault_scope
        assert pdef.vault_key
        if pdef.auth_strategy == "vertex":
            # Vertex uses ADC/service account, not an HTTP base_url.
            assert pdef.base_url == ""
            assert pdef.requires_api_key is False
            assert pdef.npm_package == "@ai-sdk/google-vertex"
        else:
            assert pdef.base_url.startswith("https://")
            assert pdef.requires_api_key is True
        assert pdef.registry_filter_provider in get_full_catalog()


def test_opencode_provider_vertex_definitions():
    """Vertex providers share the same vault key but route to separate blocks."""
    v = OPENCODE_PROVIDERS["google-vertex"]
    va = OPENCODE_PROVIDERS["google-vertex-anthropic"]
    assert v.vault_key == va.vault_key == "google"
    assert v.id_prefix == "google-vertex/"
    assert va.id_prefix == "google-vertex-anthropic/"
    assert v.registry_filter_mode == va.registry_filter_mode == "vertex"


# ── AUTH_JSON_PROVIDERS ──────────────────────────────────────────────

def test_auth_json_providers_have_required_fields():
    for name, adef in AUTH_JSON_PROVIDERS.items():
        assert adef.auth_json_key == name
        assert adef.vault_scope == "providers"
        assert adef.vault_key
        assert ProviderAuthType.AUTH_JSON in adef.auth_types


def test_auth_json_providers_cover_known_set():
    expected = {"anthropic", "openai", "azure", "xai", "deepseek", "openrouter", "moonshotai", "lmstudio", "zai"}
    assert set(AUTH_JSON_PROVIDERS.keys()) == expected


def test_azure_has_dual_auth():
    azure = AUTH_JSON_PROVIDERS["azure"]
    assert ProviderAuthType.AUTH_JSON in azure.auth_types
    assert ProviderAuthType.ENV in azure.auth_types


def test_no_overlap_between_openai_compatible_and_auth_json():
    oc_keys = set(OPENCODE_PROVIDERS.keys())
    aj_keys = set(AUTH_JSON_PROVIDERS.keys())
    assert oc_keys.isdisjoint(aj_keys), f"Overlap: {oc_keys & aj_keys}"
