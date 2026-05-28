import json

from dashboard.lib import opencode_service


def test_resolve_opencode_agent_model_uses_runtime_config(tmp_path):
    config_dir = tmp_path / ".agents"
    config_dir.mkdir()
    (config_dir / "config.json").write_text(
        json.dumps(
            {
                "runtime": {
                    "master_agent_model": "google/gemini-3.1-pro-preview-customtools",
                },
                "providers": {
                    "google": {
                        "deployment_mode": "vertex",
                    },
                },
            }
        )
    )

    model = opencode_service._resolve_opencode_agent_model({}, tmp_path)

    assert model == "google-vertex/gemini-3.1-pro-preview"


def test_resolve_opencode_agent_model_prefers_env_override(tmp_path):
    model = opencode_service._resolve_opencode_agent_model(
        {"OSTWIN_OPENCODE_AGENT_MODEL": "google-vertex/gemini-3.5-flash"},
        tmp_path,
    )

    assert model == "google-vertex/gemini-3.5-flash"
