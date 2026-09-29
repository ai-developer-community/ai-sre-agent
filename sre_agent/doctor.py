"""Run explicit live read/model smoke checks. Never prints credential values."""

import asyncio

import google.auth
from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query
from google.auth.transport.requests import Request

from sre_agent.config import Settings
from sre_agent.telemetry import Telemetry


async def check_model(settings):
    import tempfile

    if not settings.claude_model:
        raise RuntimeError("CLAUDE_MODEL is not set")
    env = {
        "CLAUDE_CODE_USE_VERTEX": "1" if settings.agent_provider == "vertex" else "0",
        "CLAUDE_CODE_USE_BEDROCK": "0",
        "CLAUDE_CODE_USE_FOUNDRY": "0",
        "CLOUD_ML_REGION": settings.vertex_region,
        "ANTHROPIC_VERTEX_PROJECT_ID": settings.project_id,
        "ANTHROPIC_API_KEY": settings.anthropic_api_key,
        "CLAUDE_CODE_OAUTH_TOKEN": "",
        "ANTHROPIC_AUTH_TOKEN": "",
    }
    with tempfile.TemporaryDirectory(prefix="sre-doctor-") as path:
        env["CLAUDE_CONFIG_DIR"] = path
        async with asyncio.timeout(60):
            async for msg in query(
                prompt="Reply with exactly READY.",
                options=ClaudeAgentOptions(
                    model=settings.claude_model,
                    tools=[],
                    setting_sources=[],
                    skills=[],
                    strict_mcp_config=True,
                    env=env,
                    cwd=path,
                    max_turns=1,
                ),
            ):
                if isinstance(msg, ResultMessage):
                    if msg.is_error or (msg.result or "").strip() != "READY":
                        raise RuntimeError("Model did not return READY")
                    return
    raise RuntimeError("No final model result")


def main():
    settings = Settings()
    failures = []
    checks = {
        "Google ADC": lambda: google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )[0].refresh(Request()),
        "Shop revision read": Telemetry(settings).revisions,
        "Shop log read": Telemetry(settings).logs,
        "Shop metric read": Telemetry(settings).metrics,
        "Claude model": lambda: asyncio.run(check_model(settings)),
    }
    for name, check in checks.items():
        try:
            check()
            print(f"PASS {name}")
        except Exception as exc:
            failures.append(name)
            print(
                f"FAIL {name}: {type(exc).__name__}. Check credentials, resource and model access."
            )
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
