import runpy
from pathlib import Path

import pytest


def test_rollback_access_is_bound_only_to_shop(monkeypatch):
    path = Path(__file__).resolve().parents[1] / "scripts/cloud"
    monkeypatch.syspath_prepend(str(path))
    module = runpy.run_path(str(path / "access.py"))
    calls = []

    def fake(*args, **kwargs):
        calls.append(args)
        if args[:3] == ("iam", "roles", "list"):
            return []
        return ""

    module["rollback_access"].__globals__["gcloud"] = fake
    module["rollback_access"]()
    bindings = [args for args in calls if "add-iam-policy-binding" in args]
    assert len(bindings) == 2
    assert all(
        args[:4] == ("run", "services", "add-iam-policy-binding", "sre-demo-shop")
        for args in bindings
    )
    create = next(args for args in calls if args[:3] == ("iam", "roles", "create"))
    assert create[create.index("--permissions") + 1] == "run.services.get,run.services.update"
    assert not any("allUsers" in str(args) or "roles/run.admin" in str(args) for args in calls)


def test_browser_access_grants_only_named_operator_and_iap_identity(monkeypatch):
    path = Path(__file__).resolve().parents[1] / "scripts/cloud"
    monkeypatch.syspath_prepend(str(path))
    module = runpy.run_path(str(path / "access.py"))
    calls = []

    def fake(*args, **kwargs):
        calls.append(args)
        return "1234"

    module["browser_access"].__globals__["gcloud"] = fake
    with pytest.raises(SystemExit):
        module["browser_access"]("")
    assert calls == []
    module["browser_access"]("operator@example.com")
    bindings = [args for args in calls if "add-iam-policy-binding" in args]
    assert len(bindings) == 2
    assert "serviceAccount:service-1234@gcp-sa-iap.iam.gserviceaccount.com" in bindings[0]
    assert "sre-demo-console" in bindings[0]
    assert "user:operator@example.com" in bindings[1]
    assert "sre-demo-console" in bindings[1]
    assert not any(
        "allUsers" in str(args) or "allAuthenticatedUsers" in str(args) for args in calls
    )
