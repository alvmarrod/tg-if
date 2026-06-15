from __future__ import annotations

import json
from pathlib import Path


import structlog

from domain.entities import MediaConfigRule, MediaScope


logger = structlog.get_logger()


_KNOWN_TYPES = {"gif", "image", "audio", "video", "voice", "sticker", "document"}


def _type_matches(rule_types: list[str], media_type: str | None) -> bool:
    if "all" in rule_types:
        return True
    if media_type is None:
        return False
    for t in rule_types:
        if t in media_type:
            return True
    return False


class MediaConfigManager:
    def __init__(self, persist_path: str = "/data/media/media_config.json") -> None:
        self._path = Path(persist_path)
        self._rules: list[MediaConfigRule] = []
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text())
            self._rules = [MediaConfigRule.model_validate(r) for r in raw]
            logger.info(
                "media config loaded", path=str(self._path), count=len(self._rules)
            )
        except Exception:
            logger.warning(
                "media config load failed", path=str(self._path), exc_info=True
            )

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            data = [r.model_dump() for r in self._rules]
            self._path.write_text(json.dumps(data, indent=2))
        except Exception:
            logger.exception("media config save failed", path=str(self._path))

    def add_rule(self, rule: MediaConfigRule) -> None:
        self._rules.append(rule)
        self._save()
        logger.info(
            "media rule added",
            scope=rule.scope,
            scope_id=rule.scope_id,
            types=rule.content_types,
            action=rule.action,
        )

    def remove_rule(
        self,
        scope: str,
        scope_id: str | None = None,
        content_types: list[str] | None = None,
    ) -> int:
        before = len(self._rules)
        self._rules = [
            r
            for r in self._rules
            if not (
                r.scope == scope
                and r.scope_id == scope_id
                and (content_types is None or r.content_types == content_types)
            )
        ]
        removed = before - len(self._rules)
        if removed:
            self._save()
            logger.info("media rule removed", count=removed)
        return removed

    def list_rules(self) -> list[MediaConfigRule]:
        return list(self._rules)

    def evaluate(
        self,
        chat_id: int,
        user_id: int,
        media_type: str | None,
    ) -> bool:
        """Returns True if the media should be eagerly downloaded, False for lazy."""
        if media_type is None:
            return False

        chat_str = str(chat_id)
        user_str = str(user_id)

        user_match: MediaConfigRule | None = None
        chat_match: MediaConfigRule | None = None
        global_match: MediaConfigRule | None = None

        for rule in self._rules:
            if not _type_matches(rule.content_types, media_type):
                continue

            if rule.scope == MediaScope.USER and rule.scope_id == user_str:
                user_match = rule
            elif rule.scope == MediaScope.CHAT and rule.scope_id == chat_str:
                chat_match = rule
            elif rule.scope == MediaScope.GLOBAL:
                global_match = rule

        # Precedence: user > chat > global > default (lazy)
        winner = user_match or chat_match or global_match
        if winner is None:
            return False
        return winner.action == "eager"
