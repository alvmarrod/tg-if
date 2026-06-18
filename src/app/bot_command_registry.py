from domain.entities import (
    BotCommandRegistration,
    SubscriberCommandResponse,
)


class BotCommandRegistry:
    def __init__(self) -> None:
        self._registrations: dict[str, dict[str, BotCommandRegistration]] = {}

    def register(
        self,
        bot_id: str,
        subscriber_id: str,
        commands: list[dict[str, str]],
    ) -> SubscriberCommandResponse:
        incoming_names = {c["command"] for c in commands if "command" in c}
        if not incoming_names:
            return SubscriberCommandResponse(
                status="nok",
                conflicts=["no valid commands provided (missing 'command' key)"],
            )

        bot_regs = self._registrations.get(bot_id, {})
        conflicts: list[str] = []
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
            BotCommandRegistration(subscriber_id=subscriber_id, commands=commands)
        )

        return SubscriberCommandResponse(status="ok", registered=sorted(incoming_names))

    def deregister(
        self,
        bot_id: str,
        subscriber_id: str,
    ) -> SubscriberCommandResponse:
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

        removed = [c["command"] for c in reg.commands if "command" in c]
        return SubscriberCommandResponse(status="ok", registered=sorted(removed))

    def get_commands(self, bot_id: str) -> list[dict[str, str]]:
        bot_regs = self._registrations.get(bot_id, {})
        merged: list[dict[str, str]] = []
        seen_names: set[str] = set()
        for subscriber_id in sorted(bot_regs):
            reg = bot_regs[subscriber_id]
            for cmd in reg.commands:
                name = cmd.get("command")
                if name and name not in seen_names:
                    seen_names.add(name)
                    merged.append(cmd)
        return merged
