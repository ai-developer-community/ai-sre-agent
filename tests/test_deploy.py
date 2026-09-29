import pytest

from scripts.cloud import demo


def test_deployment_selects_created_revision_when_ready_still_points_to_rollback(monkeypatch):
    observed = []

    def revision(*args, **kwargs):
        observed.append(args[3])
        return {
            "metadata": {"labels": {"serving.knative.dev/service": demo.SERVICE}},
            "spec": {
                "containers": [
                    {
                        "env": [
                            {"name": "APP_VERSION", "value": "v2-broken"},
                            {"name": "FAIL_RATE", "value": "1"},
                        ]
                    }
                ]
            },
        }

    monkeypatch.setattr(demo, "gcloud", revision)
    service = {
        "status": {
            "latestCreatedRevisionName": "new-broken",
            "latestReadyRevisionName": "old-healthy",
        }
    }
    assert demo.deployed_revision(service, True) == "new-broken"
    assert observed == ["new-broken"]
    with pytest.raises(SystemExit, match="does not match"):
        demo.deployed_revision(service, False)
