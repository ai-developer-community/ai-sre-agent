import json

import pytest

from shop.app import create_app


def test_healthy_checkout_and_structured_log(monkeypatch, capsys):
    monkeypatch.setenv("FAIL_RATE", "0")
    monkeypatch.setenv("K_REVISION", "shop-good")
    client = create_app().test_client()
    assert client.get("/products").status_code == 200
    result = client.post("/checkout")
    assert result.status_code == 200
    assert result.json["status"] == "paid"
    assert result.json["revision"] == "shop-good"
    log = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert log["path"] == "/checkout"
    assert log["status"] == 200
    assert log["request_id"]


def test_broken_checkout_is_not_hidden_by_liveness(monkeypatch, capsys):
    monkeypatch.setenv("FAIL_RATE", "1")
    monkeypatch.setenv("APP_VERSION", "v2-broken")
    monkeypatch.setenv("K_REVISION", "shop-bad")
    client = create_app().test_client()
    assert client.get("/health").status_code == 200
    response = client.post("/checkout")
    assert response.status_code == 500
    assert response.json["error"] == "PaymentConfigError"
    assert response.json["revision"] == "shop-bad"
    log = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert log["severity"] == "ERROR"
    assert log["app_version"] == "v2-broken"


def test_invalid_startup_configuration(monkeypatch):
    monkeypatch.setenv("FAIL_RATE", "2")
    with pytest.raises(ValueError):
        create_app()
