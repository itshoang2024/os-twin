"""Tests for Google OAuth / ADC status handling."""

import base64
import json
from unittest.mock import patch

from dashboard.lib.settings import google_oauth


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    def __init__(self, response: _FakeResponse):
        self.response = response
        self.post_data: dict | None = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def post(self, _url: str, data: dict):
        self.post_data = data
        return self.response


def _id_token(email: str) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"email": email}).encode()).rstrip(b"=")
    return f"header.{payload.decode()}.sig"


def test_get_oauth_status_refresh_failure_marks_unauthenticated(tmp_path):
    adc_file = tmp_path / "application_default_credentials.json"
    adc_file.write_text(
        json.dumps(
            {
                "type": "authorized_user",
                "client_id": "client",
                "client_secret": "secret",
                "refresh_token": "refresh-token",
                "quota_project_id": "igot-studio",
            }
        )
    )
    fake_client = _FakeClient(_FakeResponse(400, {"error": "invalid_grant"}))

    with patch.object(google_oauth, "_ADC_FILE", adc_file), patch.object(
        google_oauth.httpx, "Client", return_value=fake_client
    ):
        status = google_oauth.get_oauth_status()

    assert status["authenticated"] is False
    assert status["error"] == "reauth_required"
    assert status["project_id"] == "igot-studio"


def test_get_oauth_status_refresh_success_marks_authenticated(tmp_path):
    adc_file = tmp_path / "application_default_credentials.json"
    adc_file.write_text(
        json.dumps(
            {
                "type": "authorized_user",
                "client_id": "client",
                "client_secret": "secret",
                "refresh_token": "refresh-token",
            }
        )
    )
    fake_client = _FakeClient(
        _FakeResponse(
            200,
            {
                "access_token": "access-token",
                "id_token": _id_token("user@example.com"),
            },
        )
    )

    with patch.object(google_oauth, "_ADC_FILE", adc_file), patch.object(
        google_oauth.httpx, "Client", return_value=fake_client
    ):
        status = google_oauth.get_oauth_status()

    assert status["authenticated"] is True
    assert status["email"] == "user@example.com"
    assert fake_client.post_data["refresh_token"] == "refresh-token"
