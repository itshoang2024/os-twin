import os

import dashboard.routes.settings as settings_routes


def test_oauth_vertex_env_uses_ostwin_managed_adc(tmp_path, monkeypatch):
    adc_file = tmp_path / "google" / "application_default_credentials.json"
    adc_file.parent.mkdir(parents=True)
    adc_file.write_text('{"type":"authorized_user","refresh_token":"token"}')
    env_file = tmp_path / ".env"
    zshrc_file = tmp_path / ".zshrc"
    service_account_file = tmp_path / "google-service-account.json"
    service_account_file.write_text("{}")

    monkeypatch.setattr(settings_routes, "_OSTWIN_DIR", tmp_path)
    monkeypatch.setattr(settings_routes, "_ENV_FILE", env_file)
    monkeypatch.setattr(settings_routes, "_ZSHRC_FILE", zshrc_file)
    monkeypatch.setattr(settings_routes, "_SA_FILE", service_account_file)
    monkeypatch.setattr(settings_routes, "get_adc_path", lambda: adc_file)
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)

    settings_routes._sync_vertex_env(
        {
            "google": {
                "enabled": True,
                "deployment_mode": "vertex",
                "project_id": "test-project",
                "vertex_location": "global",
                "vertex_auth_mode": "oauth",
            }
        }
    )

    env_content = env_file.read_text()
    assert f"GOOGLE_APPLICATION_CREDENTIALS={adc_file}" in env_content
    assert os.environ["GOOGLE_APPLICATION_CREDENTIALS"] == str(adc_file)
    assert not service_account_file.exists()
