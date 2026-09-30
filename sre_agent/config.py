from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")
    project_id: str = "personal-infrastructure-505708"
    region: str = "europe-west2"
    shop_service: str = "sre-demo-shop"
    database_url: str = "postgresql+psycopg://sre_demo:local-demo-only@127.0.0.1:55432/sre_demo"
    agent_provider: str = "vertex"
    claude_model: str = ""
    vertex_region: str = "global"
    anthropic_api_key: str = ""
    allowed_hosts: list[str] = ["localhost", "127.0.0.1", "testserver"]
    allowed_origins: list[str] = []
    subscriber_enabled: bool = False
    pubsub_subscription: str = "sre-demo-agent"
    run_timeout_seconds: int = Field(default=240, ge=10, le=600)
    rollback_revision: str = ""
    max_turns: int = Field(default=15, ge=1, le=30)
