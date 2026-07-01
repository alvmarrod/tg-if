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
    bot_token: str | None = Field(
        default=None,
        description="Bot token from BotFather for non-interactive auth",
    )
    routing_rules: list[RoutingRule] = Field(default_factory=list)


class AdminBotConfig(BaseModel):
    name: str = "__admin__"
    api_id: int
    api_hash: str
    session_file: str = "sessions/admin.session"
    bot_token: str | None = Field(
        default=None,
        description="Bot token from BotFather for non-interactive auth",
    )
    user_id: int = Field(
        ..., description="Telegram user ID that receives notifications"
    )


class AppConfig(BaseModel):
    log_level: str = Field(default="INFO")
    api_side_port: int = Field(default=8080)
    media_base_url: str = Field(
        default="http://tg-if:8080",
        description="Base URL for the /files/ media retrieval endpoint (port auto-appended from api_side_port)",
    )
    media_cache_path: str = Field(
        default="/data/media",
        description="Filesystem path for the media disk cache",
    )
    media_config_path: str = Field(
        default="/data/media/media_config.json",
        description="Filesystem path for the media config persistence file",
    )
    upload_db_path: str = Field(
        default="/data/uploads.db",
        description="SQLite database path for upload registry",
    )
    upload_storage_path: str = Field(
        default="/data/uploads",
        description="Filesystem path for uploaded file storage",
    )
    max_upload_size: int = Field(
        default=2000 * 1024 * 1024,
        description="Maximum upload file size in bytes (default 2000 MB)",
    )
    export_storage_path: str = Field(
        default="/data/exports",
        description="Filesystem path for chat export output",
    )
    broker: BrokerConfig = Field(default_factory=BrokerConfig)
    bots: list[BotConfig] = Field(default_factory=list)
    admin: AdminBotConfig | None = None


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
        admin_config: AdminBotConfig | None = None
        bots_file = Path(bots_path)
        if bots_file.exists():
            raw = json.loads(bots_file.read_text())
            for entry in raw.get("bots", []):
                bots.append(BotConfig.model_validate(entry))
            admin_data = raw.get("admin")
            if admin_data:
                admin_config = AdminBotConfig.model_validate(admin_data)
        else:
            msg = f"Bot configuration file not found: {bots_file}"
            raise FileNotFoundError(msg)

        api_side_port = cls._env_int("API_SIDE_PORT", 8080)
        raw_base = cls._env_str("MEDIA_BASE_URL", "http://tg-if")
        media_base_url = f"{raw_base}:{api_side_port}"

        return AppConfig(
            log_level=cls._env_str("LOG_LEVEL", "INFO"),
            api_side_port=api_side_port,
            media_base_url=media_base_url,
            media_cache_path=cls._env_str("MEDIA_CACHE_PATH", "/data/media"),
            media_config_path=cls._env_str(
                "MEDIA_CONFIG_PATH", "/data/media/media_config.json"
            ),
            upload_db_path=cls._env_str("UPLOAD_DB_PATH", "/data/uploads.db"),
            upload_storage_path=cls._env_str("UPLOAD_STORAGE_PATH", "/data/uploads"),
            max_upload_size=cls._env_int("MAX_UPLOAD_SIZE", 2000 * 1024 * 1024),
            export_storage_path=cls._env_str("EXPORT_STORAGE_PATH", "/data/exports"),
            broker=broker,
            bots=bots,
            admin=admin_config,
        )
