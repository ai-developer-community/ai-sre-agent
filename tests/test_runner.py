"""Mocked SDK contract checks. These do not establish live provider integration."""

import asyncio
import json
from unittest.mock import Mock

import pytest
from claude_agent_sdk import ResultMessage

from sre_agent.config import Settings
from sre_agent.runner import ALLOWED, AgentRunner


def test_missing_model_fails_before_sdk_or_cloud_access(monkeypatch):
    client = Mock()
    monkeypatch.setattr("sre_agent.runner.ClaudeSDKClient", client)
    runner = AgentRunner(Settings(_env_file=None, claude_model=""), Mock(), telemetry=Mock())
    with pytest.raises(RuntimeError, match="CLAUDE_MODEL"):
        asyncio.run(runner.run({"incident_id": 1, "question": "Health?"}))
    client.assert_not_called()


def test_sdk_tools_context_and_denial_hook(monkeypatch):
    captured = {}
    store = Mock()
    store.detail.return_value = {
        "incident": {"id": 1},
        "messages": [{"role": "assistant", "content": "Earlier evidence"}],
        "evidence": [{"id": 12, "title": "Error logs"}],
    }
    store.recent_lessons.return_value = [{"content": "Human resolution for INC-002: reverted"}]
    telemetry = Mock()
    telemetry.logs.return_value = {
        "title": "Logs",
        "url": "https://console.cloud.google.com/logs",
        "kind": "logs",
        "data": {"token": "secret-value", "count": 3},
    }
    store.save_evidence.return_value = 13

    def fake_server(**kwargs):
        captured["tools"] = {tool.name: tool for tool in kwargs["tools"]}
        return {"type": "sdk", "name": "gcp", "instance": Mock()}

    class Client:
        def __init__(self, options):
            captured["options"] = options

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def query(self, prompt):
            captured["context"] = json.loads(prompt)

        async def receive_response(self):
            yield ResultMessage(
                subtype="success",
                duration_ms=1,
                duration_api_ms=1,
                is_error=False,
                num_turns=1,
                session_id="mock",
                result="Diagnosis supported by logs",
            )

    monkeypatch.setattr("sre_agent.runner.create_sdk_mcp_server", fake_server)
    monkeypatch.setattr("sre_agent.runner.ClaudeSDKClient", Client)
    runner = AgentRunner(Settings(_env_file=None, claude_model="test-model"), store, telemetry)
    assert asyncio.run(runner.run({"incident_id": 1, "question": "What changed?"})) == (
        "Diagnosis supported by logs"
    )
    options = captured["options"]
    assert options.tools == []
    assert options.setting_sources == []
    assert options.strict_mcp_config is True
    assert set(options.allowed_tools) == set(ALLOWED)
    assert set(captured["tools"]) == {
        "read_logs",
        "read_metrics",
        "read_revisions",
        "read_deploy_events",
    }
    assert options.env["CLAUDE_CODE_USE_VERTEX"] == "1"
    assert options.env["ANTHROPIC_API_KEY"] == ""
    context = captured["context"]
    assert context["history"][0]["content"] == "Earlier evidence"
    assert context["past_evidence"][0]["id"] == 12
    assert context["lessons"][0]["content"].startswith("Human resolution")
    hook = options.hooks["PreToolUse"][0].hooks[0]
    assert asyncio.run(hook({"tool_name": ALLOWED[0]}, None, None)) == {}
    for forbidden in ["Bash", "Write", "mcp__gcp__rollback", "mcp__other__read_logs"]:
        denied = asyncio.run(hook({"tool_name": forbidden}, None, None))
        assert denied["hookSpecificOutput"]["permissionDecision"] == "deny"
    result = asyncio.run(captured["tools"]["read_logs"].handler({"minutes": 5}))
    assert json.loads(result["content"][0]["text"])["data"]["token"] == "[redacted]"
    store.save_evidence.assert_called_once()
    telemetry.logs.side_effect = PermissionError("API_KEY=do-not-leak")
    result = asyncio.run(captured["tools"]["read_logs"].handler({"minutes": 5}))
    assert result["is_error"] is True
    assert "Do not infer health" in result["content"][0]["text"]
    assert "do-not-leak" not in str(result)
