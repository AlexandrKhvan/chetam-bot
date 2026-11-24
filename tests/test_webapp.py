from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.web.auth import verify_telegram_init_data
from app.web.server import create_app


def _make_init_data(bot_token: str, user_id: int = 777, first_name: str = "Alex") -> str:
    params = {
        "auth_date": str(int(time.time())),
        "query_id": "AAHdF6IQAAAAAN0XohDhrOrc",
        "user": json.dumps({"id": user_id, "first_name": first_name, "username": "alex"}),
    }
    data_check_string = "\n".join(f"{k}={params[k]}" for k in sorted(params.keys()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    sig = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    params["hash"] = sig
    return urlencode(params)


def test_verify_telegram_init_data_valid_and_invalid():
    token = "123456:TEST_TOKEN"
    raw = _make_init_data(token, user_id=42, first_name="Alex")
    user = verify_telegram_init_data(raw, token)
    assert user.user_id == 42
    assert user.first_name == "Alex"

    with pytest.raises(ValueError):
        verify_telegram_init_data(raw, "999999:WRONG_TOKEN")


def test_webapp_api_end_to_end(tmp_path):
    token = "123456:TEST_TOKEN"
    settings = Settings(
        BOT_TOKEN=token,
        DATABASE_PATH=tmp_path / "webapp_test.db",
        ALLOWED_USER_IDS="777",
    )
    app = create_app(settings)
    headers = {"X-Telegram-Init-Data": _make_init_data(token, user_id=777)}

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/api/me").status_code == 401

        # Forbidden for non-allowed user
        bad_headers = {"X-Telegram-Init-Data": _make_init_data(token, user_id=999)}
        assert client.get("/api/me", headers=bad_headers).status_code == 403

        me = client.get("/api/me", headers=headers)
        assert me.status_code == 200
        today = me.json()["today"]

        # Brain-dump multiple tasks via API
        dump_res = client.post(
            "/api/tasks/dump",
            headers=headers,
            json={"text": "надо сделать лабу, потом купить кофе и срочно отправить отчёт"},
        )
        assert dump_res.status_code == 200
        assert dump_res.json()["count"] == 3
        first_id = dump_res.json()["created"][0]["id"]

        # Plan and toggle first task
        plan_res = client.post(
            f"/api/tasks/{first_id}/plan",
            headers=headers,
            json={"target_date": today},
        )
        assert plan_res.status_code == 200
        tog_res = client.post(f"/api/tasks/{first_id}/toggle", headers=headers)
        assert tog_res.status_code == 200
        assert tog_res.json()["task"]["status"] == "done"

        day_res = client.get(f"/api/day?date={today}", headers=headers)
        assert day_res.status_code == 200
        assert day_res.json()["done_items"] == 1
