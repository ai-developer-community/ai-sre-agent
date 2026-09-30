import asyncio
import json
import logging
import tempfile

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKClient,
    HookMatcher,
    PermissionResultDeny,
    ResultMessage,
    create_sdk_mcp_server,
    tool,
)

from sre_agent.config import ROOT
from sre_agent.telemetry import Telemetry, sanitize

logger = logging.getLogger(__name__)
TOOL_NAMES = ("read_logs", "read_metrics", "read_revisions", "read_deploy_events")
ALLOWED = [f"mcp__gcp__{name}" for name in TOOL_NAMES]


async def deny_unknown(name, input_, context):
    return PermissionResultDeny(message="Only the explicitly approved read tools are available.")


class AgentRunner:
    def __init__(self, settings, store, telemetry=None):
        self.settings = settings
        self.store = store
        self.telemetry = telemetry or Telemetry(settings)

    async def run(self, run):
        s = self.settings
        if not s.claude_model:
            raise RuntimeError("Set CLAUDE_MODEL to a model enabled for your provider, then retry.")
        if s.agent_provider not in ("vertex", "anthropic"):
            raise RuntimeError("AGENT_PROVIDER must be vertex or anthropic")
        if s.agent_provider == "anthropic" and not s.anthropic_api_key:
            raise RuntimeError("Set ANTHROPIC_API_KEY for the selected API provider.")
        incident_id = run["incident_id"]

        async def invoke(name, fn, **args):
            self.store.event(incident_id, "tool_started", f"Checking {name}", name, args)
            logger.info(
                json.dumps({"audit": True, "tool": name, "input": args, "incident_id": incident_id})
            )
            try:
                result = await asyncio.to_thread(fn, **args)
                result = sanitize(result)
                evidence_id = self.store.save_evidence(incident_id, **result)
                self.store.event(
                    incident_id,
                    "tool_completed",
                    result["title"],
                    name,
                    {"evidence_id": evidence_id},
                )
                return {"content": [{"type": "text", "text": json.dumps(result)}]}
            except Exception as exc:
                logger.exception("Read tool failed")
                message = f"{name} unavailable ({type(exc).__name__}). Do not infer health."
                self.store.event(incident_id, "tool_failed", message, name)
                return {"is_error": True, "content": [{"type": "text", "text": message}]}

        @tool(
            "read_logs",
            "Read a bounded log sample over 5-1440 minutes; never count samples as traffic "
            "totals. errors_only=false includes other endpoints.",
            {"minutes": int, "errors_only": bool},
        )
        async def read_logs(args):
            return await invoke(
                "read_logs",
                self.telemetry.logs,
                minutes=args.get("minutes", 30),
                errors_only=args.get("errors_only", True),
            )

        @tool(
            "read_metrics",
            "Read Cloud Run request counts over 5-1440 minutes. Use total_requests only when "
            "summary_complete is true; points are a bounded sample.",
            {"minutes": int},
        )
        async def read_metrics(args):
            return await invoke(
                "read_metrics", self.telemetry.metrics, minutes=args.get("minutes", 15)
            )

        @tool("read_revisions", "Read serving traffic and recent exact revision names.", {})
        async def read_revisions(args):
            return await invoke("read_revisions", self.telemetry.revisions)

        @tool(
            "read_deploy_events",
            "Read deployment audit timestamps over 5-1440 minutes, not secret configs.",
            {"minutes": int},
        )
        async def read_deploy_events(args):
            return await invoke(
                "read_deploy_events", self.telemetry.deploy_logs, minutes=args.get("minutes", 60)
            )

        async def guard(input_, tool_use_id, context):
            name = input_.get("tool_name", "")
            if name not in ALLOWED:
                self.store.event(incident_id, "tool_denied", f"Blocked tool: {name}")
                return {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": "Read tools only",
                    }
                }
            return {}

        server = create_sdk_mcp_server(
            name="gcp",
            version="1.0.0",
            tools=[read_logs, read_metrics, read_revisions, read_deploy_events],
        )
        env = {
            "CLAUDE_CODE_USE_VERTEX": "1" if s.agent_provider == "vertex" else "0",
            "CLAUDE_CODE_USE_BEDROCK": "0",
            "CLAUDE_CODE_USE_FOUNDRY": "0",
            "ANTHROPIC_VERTEX_PROJECT_ID": s.project_id,
            "CLOUD_ML_REGION": s.vertex_region,
            "ANTHROPIC_API_KEY": s.anthropic_api_key if s.agent_provider == "anthropic" else "",
            "CLAUDE_CODE_OAUTH_TOKEN": "",
            "ANTHROPIC_AUTH_TOKEN": "",
        }
        detail = self.store.detail(incident_id)
        context = {
            "service": s.shop_service,
            "region": s.region,
            "project": s.project_id,
            "incident": detail["incident"],
            "history": detail["messages"][-20:],
            "past_evidence": detail["evidence"][-8:],
            "lessons": self.store.recent_lessons(),
            "request": run["question"],
        }
        # An isolated cwd/config prevents loading the operator's local Claude plugins/settings.
        with tempfile.TemporaryDirectory(prefix="sre-agent-") as work:
            env["CLAUDE_CONFIG_DIR"] = work
            options = ClaudeAgentOptions(
                model=s.claude_model,
                system_prompt=(ROOT / "sre_agent/prompts/triage.md").read_text(),
                cwd=work,
                env=env,
                tools=[],
                setting_sources=[],
                skills=[],
                strict_mcp_config=True,
                mcp_servers={"gcp": server},
                allowed_tools=ALLOWED,
                can_use_tool=deny_unknown,
                disallowed_tools=[
                    "Bash",
                    "Read",
                    "Write",
                    "Edit",
                    "WebFetch",
                    "WebSearch",
                    "Agent",
                ],
                hooks={"PreToolUse": [HookMatcher(hooks=[guard])]},
                max_turns=s.max_turns,
                max_budget_usd=2.0,
            )
            async with asyncio.timeout(s.run_timeout_seconds):
                async with ClaudeSDKClient(options=options) as client:
                    await client.query(json.dumps(context, default=str))
                    async for message in client.receive_response():
                        if isinstance(message, ResultMessage):
                            if message.is_error or not message.result:
                                raise RuntimeError(
                                    "Agent did not complete. Check provider access or limits."
                                )
                            return message.result
        raise RuntimeError("Agent ended without a diagnosis")
