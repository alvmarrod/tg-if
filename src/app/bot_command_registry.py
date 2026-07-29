import re

from domain.entities import (
    BotCommandRegistration,
    SubscriberCommandResponse,
)

_VALID_COMMAND_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


def _normalize_command(name: str) -> str:
    """Normalize a command name by replacing hyphens with underscores."""
    return name.replace("-", "_")


class BotCommandRegistry:
    def __init__(self) -> None:
        """Initialize the registry with empty storage."""
        self._registrations: dict[str, dict[str, BotCommandRegistration]] = {}

    def register(
        self,
        bot_id: str,
        subscriber_id: str,
        commands: list[dict[str, str]],
    ) -> SubscriberCommandResponse:
        """Register commands for a subscriber on a bot.

        Args:
            bot_id: The bot identifier
            subscriber_id: The subscriber identifier
            commands: List of command dictionaries

        Returns:
            SubscriberCommandResponse with status and results/errors
        """
        normalized: list[dict[str, str]] = []
        original_names: set[str] = set()
        skipped: list[str] = []
        for cmd in commands:
            if "command" not in cmd:
                skipped.append(cmd.get("command", "unknown"))
                continue
            original = cmd["command"]
            original_names.add(original)
            new_cmd = dict(cmd)
            new_cmd["command"] = _normalize_command(original)
            normalized.append(new_cmd)

        if skipped:
            return SubscriberCommandResponse(
                status="nok",
                conflicts=[f"command '{cmd}' missing 'command' key" for cmd in skipped],
            )

        incoming_names = {c["command"] for c in normalized}
        if not incoming_names:
            return SubscriberCommandResponse(
                status="nok",
                conflicts=["no valid commands provided (missing 'command' key)"],
            )

        conflicts: list[str] = []
        for name in sorted(incoming_names):
            if not _VALID_COMMAND_RE.match(name):
                conflicts.append(
                    f"command '{name}' is invalid — only lowercase "
                    f"letters, digits, and underscores allowed"
                )

        if conflicts:
            return SubscriberCommandResponse(status="nok", conflicts=conflicts)

        bot_regs = self._registrations.get(bot_id, {})
        for other_id, other_reg in bot_regs.items():
            if other_id == subscriber_id:
                continue
            other_names = {c["command"] for c in other_reg.commands if "command" in c}
            overlap = incoming_names & other_names
            for name in sorted(overlap):
                conflicts.append(
                    f"command '{name}' already registered by subscriber '{other_id}'"
                )

        if conflicts:
            return SubscriberCommandResponse(status="nok", conflicts=conflicts)

        self._registrations.setdefault(bot_id, {})[subscriber_id] = (
            BotCommandRegistration(subscriber_id=subscriber_id, commands=normalized)
        )

        return SubscriberCommandResponse(status="ok", registered=sorted(original_names))

    def deregister(
        self,
        bot_id: str,
        subscriber_id: str,
    ) -> SubscriberCommandResponse:
        """Remove a subscriber's commands from a bot.

        Args:
            bot_id: The bot identifier
            subscriber_id: The subscriber identifier

        Returns:
            SubscriberCommandResponse with status and results/errors
        """
        bot_regs = self._registrations.get(bot_id, {})
        reg = bot_regs.pop(subscriber_id, None)
        if reg is None:
            return SubscriberCommandResponse(
                status="nok",
                conflicts=[
                    f"no registration found for subscriber '{subscriber_id}' on bot '{bot_id}'"
                ],
            )

        if not bot_regs:
            del self._registrations[bot_id]

        removed = [c["command"] for c in reg.commands]
        return SubscriberCommandResponse(status="ok", registered=sorted(removed))

    def get_commands(self, bot_id: str) -> list[dict[str, str]]:
        """Get all unique commands registered for a bot.

        Args:
            bot_id: The bot identifier

        Returns:
            List of unique command dictionaries
        """
        bot_regs = self._registrations.get(bot_id, {})
        merged: list[dict[str, str]] = []
        seen_names: set[str] = set()
        for subscriber_id in sorted(bot_regs):
            reg = bot_regs[subscriber_id]
            for cmd in reg.commands:
                name = cmd["command"]
                if name not in seen_names:
                    seen_names.add(name)
                    merged.append(cmd)
        return merged
