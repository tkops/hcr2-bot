from __future__ import annotations

import sys

import typer
from modules.common import is_help_request, print_command_help, print_unknown_entity

from hcr2.cli.registry import ENTITY_REGISTRY, ENTITY_SPECS, EntitySpec, root_commands
from hcr2.output import status


TYPER_ROOT_OPTIONS = {"--install-completion", "--show-completion"}


def _make_entity_command(spec: EntitySpec):
    def command(ctx: typer.Context) -> None:
        CliApp().dispatch([spec.name, *ctx.args])

    command.__name__ = f"{spec.name.replace('-', '_')}_command"
    return command


typer_app = typer.Typer(
    add_help_option=False,
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
    invoke_without_command=True,
    no_args_is_help=False,
    add_completion=True,
    rich_markup_mode=None,
)


for entity_spec in ENTITY_SPECS:
    typer_app.command(
        name=entity_spec.name,
        help=entity_spec.description,
        add_help_option=False,
        context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
    )(_make_entity_command(entity_spec))


class CliApp:
    def show_main_help(self) -> None:
        print_command_help(
            usage="hcr2.py <entity> <command> [options]",
            commands=root_commands(),
            notes=[
                "Prefer flags for IDs, filters and optional values, e.g. --id, --season, --all, --team.",
                "Older positional forms still work as legacy aliases.",
            ],
        )

    def show_entity_help(self, entity: str) -> None:
        spec = ENTITY_REGISTRY.get(entity)
        if spec is None:
            print_unknown_entity(entity)
            self.show_main_help()
            return

        spec.print_help()

    def dispatch(self, argv: list[str]) -> None:
        if not argv:
            self.show_main_help()
            return

        entity = argv[0]
        if is_help_request(entity):
            self.show_main_help()
            return

        if entity == "help":
            self._dispatch_help_command(argv[1:])
            return

        spec = ENTITY_REGISTRY.get(entity)
        if spec is None:
            print_unknown_entity(entity)
            self.show_main_help()
            return

        if spec.handler is not None and len(argv) == 1:
            spec.handler([])
            return

        if len(argv) == 1:
            spec.print_help()
            return

        command = argv[1]
        args = argv[2:]

        if command == "help" or is_help_request(command):
            spec.print_help()
            return

        spec.handle_command(command, args)

    def _dispatch_help_command(self, args: list[str]) -> None:
        if not args or is_help_request(args[0]):
            self.show_main_help()
            return

        self.show_entity_help(args[0])


def main(argv: list[str] | None = None) -> None:
    """Run one command and exit non-zero if it reported an error.

    See hcr2/output/status.py for why the exit code is derived from the output.
    """
    argv = sys.argv[1:] if argv is None else argv

    writer = status.ErrorSniffingWriter(sys.stdout)
    original_stdout = sys.stdout
    status.reset()
    sys.stdout = writer
    try:
        _dispatch(argv)
    finally:
        writer.finish()
        sys.stdout = original_stdout

    if writer.saw_error or status.failure_marked():
        sys.exit(status.EXIT_FAILURE)


def _dispatch(argv: list[str]) -> None:
    if _should_use_legacy_dispatch(argv):
        CliApp().dispatch(argv)
        return

    typer_app(args=argv, prog_name="hcr2.py", standalone_mode=False)


def _should_use_legacy_dispatch(argv: list[str]) -> bool:
    if not argv:
        return True
    if argv[0] in TYPER_ROOT_OPTIONS:
        return False
    if is_help_request(argv[0]) or argv[0] == "help":
        return True
    return argv[0] not in ENTITY_REGISTRY
