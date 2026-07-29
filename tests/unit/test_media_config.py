from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.media_config import MediaConfigManager, _type_matches
from domain.entities import MediaConfigRule, MediaScope


class TestTypeMatches:
    def test_wildcard_matches_any(self) -> None:
        assert _type_matches(["all"], "photo") is True
        assert _type_matches(["all"], "video") is True

    def test_wildcard_matches_none(self) -> None:
        assert _type_matches(["all"], None) is True

    def test_exact_type_match(self) -> None:
        assert _type_matches(["photo"], "photo") is True

    def test_partial_type_match(self) -> None:
        assert _type_matches(["doc"], "document") is True

    def test_no_match(self) -> None:
        assert _type_matches(["photo"], "video") is False

    def test_no_match_none_type(self) -> None:
        assert _type_matches(["photo"], None) is False

    def test_multiple_types_one_matches(self) -> None:
        assert _type_matches(["photo", "video", "audio"], "audio") is True

    def test_multiple_types_none_match(self) -> None:
        assert _type_matches(["photo", "video"], "sticker") is False

    def test_empty_list_returns_false(self) -> None:
        assert _type_matches([], "photo") is False

    def test_empty_list_with_none(self) -> None:
        assert _type_matches([], None) is False


class TestMediaConfigManager:
    def test_default_state(self, tmp_path: Path) -> None:
        mgr = MediaConfigManager(str(tmp_path / "config.json"))
        assert mgr.list_rules() == []

    def test_add_and_list_rules(self, tmp_path: Path) -> None:
        mgr = MediaConfigManager(str(tmp_path / "config.json"))
        rule = MediaConfigRule(
            scope=MediaScope.GLOBAL,
            content_types=["photo"],
            action="eager",
        )
        mgr.add_rule(rule)
        rules = mgr.list_rules()
        assert len(rules) == 1
        assert rules[0].scope == MediaScope.GLOBAL

    def test_add_multiple_rules(self, tmp_path: Path) -> None:
        mgr = MediaConfigManager(str(tmp_path / "config.json"))
        mgr.add_rule(
            MediaConfigRule(
                scope=MediaScope.GLOBAL, content_types=["all"], action="eager"
            )
        )
        mgr.add_rule(
            MediaConfigRule(
                scope=MediaScope.CHAT,
                scope_id="-100",
                content_types=["video"],
                action="lazy",
            )
        )
        assert len(mgr.list_rules()) == 2

    def test_remove_rule_by_scope(self, tmp_path: Path) -> None:
        mgr = MediaConfigManager(str(tmp_path / "config.json"))
        mgr.add_rule(
            MediaConfigRule(
                scope=MediaScope.GLOBAL, content_types=["all"], action="eager"
            )
        )
        removed = mgr.remove_rule("global")
        assert removed == 1
        assert mgr.list_rules() == []

    def test_remove_rule_by_scope_and_id(self, tmp_path: Path) -> None:
        mgr = MediaConfigManager(str(tmp_path / "config.json"))
        mgr.add_rule(
            MediaConfigRule(
                scope=MediaScope.CHAT,
                scope_id="-100",
                content_types=["all"],
                action="eager",
            )
        )
        removed = mgr.remove_rule("chat", scope_id="-100")
        assert removed == 1

    def test_remove_rule_non_existent(self, tmp_path: Path) -> None:
        mgr = MediaConfigManager(str(tmp_path / "config.json"))
        removed = mgr.remove_rule("global")
        assert removed == 0

    def test_remove_rule_by_content_types(self, tmp_path: Path) -> None:
        mgr = MediaConfigManager(str(tmp_path / "config.json"))
        mgr.add_rule(
            MediaConfigRule(
                scope=MediaScope.GLOBAL, content_types=["audio"], action="lazy"
            )
        )
        removed = mgr.remove_rule("global", content_types=["audio"])
        assert removed == 1

    def test_evaluate_no_rules_returns_false(self, tmp_path: Path) -> None:
        mgr = MediaConfigManager(str(tmp_path / "config.json"))
        assert mgr.evaluate(chat_id=123, user_id=456, media_type="photo") is False

    def test_evaluate_global_eager(self, tmp_path: Path) -> None:
        mgr = MediaConfigManager(str(tmp_path / "config.json"))
        mgr.add_rule(
            MediaConfigRule(
                scope=MediaScope.GLOBAL, content_types=["photo"], action="eager"
            )
        )
        assert mgr.evaluate(chat_id=1, user_id=2, media_type="photo") is True

    def test_evaluate_global_lazy(self, tmp_path: Path) -> None:
        mgr = MediaConfigManager(str(tmp_path / "config.json"))
        mgr.add_rule(
            MediaConfigRule(
                scope=MediaScope.GLOBAL, content_types=["all"], action="lazy"
            )
        )
        assert mgr.evaluate(chat_id=1, user_id=2, media_type="photo") is False

    def test_evaluate_user_precedence_over_chat(self, tmp_path: Path) -> None:
        mgr = MediaConfigManager(str(tmp_path / "config.json"))
        mgr.add_rule(
            MediaConfigRule(
                scope=MediaScope.GLOBAL, content_types=["all"], action="lazy"
            )
        )
        mgr.add_rule(
            MediaConfigRule(
                scope=MediaScope.CHAT,
                scope_id="100",
                content_types=["all"],
                action="lazy",
            )
        )
        mgr.add_rule(
            MediaConfigRule(
                scope=MediaScope.USER,
                scope_id="200",
                content_types=["all"],
                action="eager",
            )
        )
        assert mgr.evaluate(chat_id=100, user_id=200, media_type="video") is True

    def test_evaluate_chat_precedence_over_global(self, tmp_path: Path) -> None:
        mgr = MediaConfigManager(str(tmp_path / "config.json"))
        mgr.add_rule(
            MediaConfigRule(
                scope=MediaScope.GLOBAL, content_types=["all"], action="eager"
            )
        )
        mgr.add_rule(
            MediaConfigRule(
                scope=MediaScope.CHAT,
                scope_id="100",
                content_types=["all"],
                action="lazy",
            )
        )
        assert mgr.evaluate(chat_id=100, user_id=1, media_type="photo") is False

    def test_evaluate_type_filter(self, tmp_path: Path) -> None:
        mgr = MediaConfigManager(str(tmp_path / "config.json"))
        mgr.add_rule(
            MediaConfigRule(
                scope=MediaScope.GLOBAL, content_types=["video"], action="eager"
            )
        )
        assert mgr.evaluate(chat_id=1, user_id=2, media_type="photo") is False
        assert mgr.evaluate(chat_id=1, user_id=2, media_type="video") is True

    def test_evaluate_type_none(self, tmp_path: Path) -> None:
        mgr = MediaConfigManager(str(tmp_path / "config.json"))
        mgr.add_rule(
            MediaConfigRule(
                scope=MediaScope.GLOBAL, content_types=["photo"], action="eager"
            )
        )
        assert mgr.evaluate(chat_id=1, user_id=2, media_type=None) is False

    def test_persistence(self, tmp_path: Path) -> None:
        path = str(tmp_path / "config.json")
        mgr1 = MediaConfigManager(path)
        mgr1.add_rule(
            MediaConfigRule(
                scope=MediaScope.GLOBAL, content_types=["all"], action="eager"
            )
        )
        mgr2 = MediaConfigManager(path)
        assert len(mgr2.list_rules()) == 1
        assert mgr2.list_rules()[0].action == "eager"

    def test_load_missing_file_uses_defaults(self, tmp_path: Path) -> None:
        mgr = MediaConfigManager(str(tmp_path / "nonexistent.json"))
        assert mgr.list_rules() == []

    def test_load_corrupt_json_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "config.json"
        path.write_text("not json", encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            MediaConfigManager(str(path))

    def test_save_failure_raises(self, tmp_path: Path) -> None:
        mgr = MediaConfigManager(str(tmp_path / "config.json"))
        rule = MediaConfigRule(
            scope=MediaScope.GLOBAL, content_types=["all"], action="eager"
        )
        with patch.object(Path, "write_text", side_effect=PermissionError("denied")):
            with pytest.raises(PermissionError):
                mgr.add_rule(rule)
