import json
import os
from pathlib import Path

from pydantic import BaseModel, Field

from domain.rules import RoutingRule


class BrokerConfig(BaseModel):
    host: str = Field(default="localhost")
    port: int = Field(default=5672)
    user: str = Field(default="guest")
    password: str = Field(default="guest")
    vhost: str = Field(default="/")


class BotConfig(BaseModel):
    name: str
    api_id: int
    api_hash: str
    session_file: str
    routing_rules: list[RoutingRule] = Field(default_factory=list)


class AppConfig(BaseModel):
    log_level: str = Field(default="INFO")
    health_port: int = Field(default=8080)
    broker: BrokerConfig = Field(default_factory=BrokerConfig)
    bots: list[BotConfig] = Field(default_factory=list)


class ConfigLoader:
    @staticmethod
    def _env_str(key: str, default: str) -> str:
        return os.environ.get(key, default)

    @staticmethod
    def _env_int(key: str, default: int) -> int:
        raw = os.environ.get(key)
        if raw is None:
            return default
        return int(raw)

    @classmethod
    def load(cls, bots_path: str | Path = "config/bots.json") -> AppConfig:
        broker = BrokerConfig(
            host=cls._env_str("RABBITMQ_HOST", "localhost"),
            port=cls._env_int("RABBITMQ_PORT", 5672),
            user=cls._env_str("RABBITMQ_USER", "guest"),
            password=cls._env_str("RABBITMQ_PASSWORD", "guest"),
            vhost=cls._env_str("RABBITMQ_VHOST", "/"),
        )

        bots: list[BotConfig] = []
        bots_file = Path(bots_path)
        if bots_file.exists():
            raw = json.loads(bots_file.read_text())
            for entry in raw.get("bots", []):
                bots.append(BotConfig.model_validate(entry))
        else:
            msg = f"Bot configuration file not found: {bots_file}"
            raise FileNotFoundError(msg)

        return AppConfig(
            log_level=cls._env_str("LOG_LEVEL", "INFO"),
            health_port=cls._env_int("HEALTH_CHECK_PORT", 8080),
            broker=broker,
            bots=bots,
        )
