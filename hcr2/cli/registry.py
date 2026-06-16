from __future__ import annotations

from dataclasses import dataclass
from types import ModuleType
from typing import Callable

import version
from modules import donations, match, matchscore, player, season, sheet, stats, teamevent, vehicle


CommandHandler = Callable[[list[str]], None]
HelpHandler = Callable[[], None]


@dataclass(frozen=True)
class EntitySpec:
    name: str
    description: str
    commands_label: str | None = None
    module: ModuleType | None = None
    handler: CommandHandler | None = None
    help_handler: HelpHandler | None = None

    def print_help(self) -> None:
        if self.help_handler is not None:
            self.help_handler()
            return
        if self.module is not None:
            self.module.print_help()
            return
        raise RuntimeError(f"No help handler configured for {self.name}")

    def handle_command(self, command: str, args: list[str]) -> None:
        if self.handler is not None:
            self.handler([command, *args])
            return
        if self.module is not None:
            self.module.handle_command(command, args)
            return
        raise RuntimeError(f"No command handler configured for {self.name}")


def _print_version_help() -> None:
    print(version.get_version())


def _handle_version(args: list[str]) -> None:
    print(version.get_version())


ENTITY_SPECS: tuple[EntitySpec, ...] = (
    EntitySpec("vehicle", "Manage vehicles", module=vehicle),
    EntitySpec("player", "Manage players", module=player),
    EntitySpec("teamevent", "Manage team events", module=teamevent),
    EntitySpec("season", "Manage seasons", module=season),
    EntitySpec("match", "Manage matches", module=match),
    EntitySpec("matchscore", "Manage match scores", module=matchscore),
    EntitySpec("stats", "Show statistics", module=stats),
    EntitySpec("sheet", "Manage Excel files for matches", module=sheet),
    EntitySpec("donations", "Manage Research Lab donations", module=donations),
    EntitySpec(
        "version",
        "Print version",
        commands_label="version",
        handler=_handle_version,
        help_handler=_print_version_help,
    ),
)

ENTITY_REGISTRY = {spec.name: spec for spec in ENTITY_SPECS}


def root_commands() -> list[tuple[str, str]]:
    commands = [(spec.commands_label or spec.name, spec.description) for spec in ENTITY_SPECS]
    commands.append(("help [entity]", "Show root or entity help"))
    return commands
