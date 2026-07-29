from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from infrastructure.config import (
    AppConfig,
    ConfigLoader,
)


class TestConfigLoader:
    def test_env_str_returns_value(self) -> None:
        with patch.dict(os.environ, {"TEST_KEY": "hello"}, clear=True):
            assert ConfigLoader._env_str("TEST_KEY") == "hello"

    def test_env_str_raises_on_missing(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="Required environment variable"):
                ConfigLoader._env_str("MISSING_KEY")

    def test_env_str_raises_on_empty(self) -> None:
        with patch.dict(os.environ, {"EMPTY_KEY": ""}, clear=True):
            with pytest.raises(ValueError, match="Required environment variable"):
                ConfigLoader._env_str("EMPTY_KEY")

    def test_env_str_returns_default(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            assert ConfigLoader._env_str("MISSING", "default_val") == "default_val"

    def test_env_int_returns_value(self) -> None:
        with patch.dict(os.environ, {"INT_KEY": "42"}, clear=True):
            assert ConfigLoader._env_int("INT_KEY") == 42

    def test_env_int_returns_default_when_missing(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            assert ConfigLoader._env_int("MISSING", 99) == 99

    def test_env_int_returns_default_when_empty(self) -> None:
        with patch.dict(os.environ, {"EMPTY": ""}, clear=True):
            assert ConfigLoader._env_int("EMPTY", 55) == 55

    def test_load_raises_on_missing_bots_file(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(FileNotFoundError, match="Bot configuration file"):
                ConfigLoader.load("nonexistent_bots.json")

    def test_load_with_minimal_config(self, tmp_path: Path) -> None:
        bots_file = tmp_path / "bots.json"
        bots_file.write_text(json.dumps({"bots": []}), encoding="utf-8")
        with patch.dict(
            os.environ,
            {
                "RABBITMQ_HOST": "rabbit",
                "RABBITMQ_PORT": "5672",
                "RABBITMQ_USER": "user",
                "RABBITMQ_PASSWORD": "pass",
            },
            clear=True,
        ):
            config = ConfigLoader.load(str(bots_file))
        assert isinstance(config, AppConfig)
        assert config.broker.host == "rabbit"
        assert config.broker.port == 5672
        assert config.broker.user == "user"
        assert config.broker.password == "pass"
        assert config.bots == []
        assert config.admin is None
        assert config.user_account is None

    def test_load_with_bots(self, tmp_path: Path) -> None:
        bots_file = tmp_path / "bots.json"
        bots_file.write_text(
            json.dumps(
                {
                    "bots": [
                        {
                            "name": "aibot",
                            "api_id": 111,
                            "api_hash": "hash",
                            "session_file": "sessions/aibot.session",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        with patch.dict(os.environ, {}, clear=True):
            config = ConfigLoader.load(str(bots_file))
        assert len(config.bots) == 1
        assert config.bots[0].name == "aibot"

    def test_load_with_admin(self, tmp_path: Path) -> None:
        bots_file = tmp_path / "bots.json"
        bots_file.write_text(
            json.dumps(
                {
                    "bots": [],
                    "admin": {
                        "api_id": 222,
                        "api_hash": "admin_hash",
                        "user_id": 12345,
                    },
                }
            ),
            encoding="utf-8",
        )
        with patch.dict(os.environ, {}, clear=True):
            config = ConfigLoader.load(str(bots_file))
        assert config.admin is not None
        assert config.admin.api_id == 222
        assert config.admin.user_id == 12345

    def test_load_with_user_account(self, tmp_path: Path) -> None:
        bots_file = tmp_path / "bots.json"
        bots_file.write_text(
            json.dumps(
                {
                    "bots": [],
                    "user": {
                        "api_id": 333,
                        "api_hash": "user_hash",
                    },
                }
            ),
            encoding="utf-8",
        )
        with patch.dict(os.environ, {}, clear=True):
            config = ConfigLoader.load(str(bots_file))
        assert config.user_account is not None
        assert config.user_account.api_id == 333

    def test_media_base_url_without_port(self, tmp_path: Path) -> None:
        bots_file = tmp_path / "bots.json"
        bots_file.write_text(json.dumps({"bots": []}), encoding="utf-8")
        with patch.dict(
            os.environ,
            {
                "MEDIA_BASE_URL": "http://tg-if",
                "API_SIDE_PORT": "8080",
            },
            clear=True,
        ):
            config = ConfigLoader.load(str(bots_file))
        assert config.media_base_url == "http://tg-if:8080"

    def test_media_base_url_with_port(self, tmp_path: Path) -> None:
        bots_file = tmp_path / "bots.json"
        bots_file.write_text(json.dumps({"bots": []}), encoding="utf-8")
        with patch.dict(
            os.environ,
            {
                "MEDIA_BASE_URL": "http://tg-if:9090",
                "API_SIDE_PORT": "8080",
            },
            clear=True,
        ):
            config = ConfigLoader.load(str(bots_file))
        assert config.media_base_url == "http://tg-if:9090"

    def test_media_base_url_with_invalid_port(self, tmp_path: Path) -> None:
        bots_file = tmp_path / "bots.json"
        bots_file.write_text(json.dumps({"bots": []}), encoding="utf-8")
        with patch.dict(
            os.environ,
            {
                "MEDIA_BASE_URL": "http://tg-if:not_a_port",
                "API_SIDE_PORT": "8080",
            },
            clear=True,
        ):
            config = ConfigLoader.load(str(bots_file))
        assert config.media_base_url == "http://tg-if:8080"
