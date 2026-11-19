"""Agate command line (implementation behind `.agate/agate.py`).

Subcommands come from the modules in `core/lib/`:
- a module that defines `register(subparsers, root)` adds its own argparse subcommands (packages, start…);
- a module that defines `PASSTHROUGH = {"name": "help"}` and `main(argv)` gets every argument after its name as is
  (mcp, chats, export keep their own sub-subcommands and `--help`).
New modules plug in without editing this file.
"""
from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path

CORE = Path(__file__).resolve().parent
LIB = CORE / "lib"
ROOT = CORE.parents[1]  # <project>/.agate/core → <project>

# Root option each passthrough tool understands (so they always act on this project).
ROOT_FLAGS = {"mcp": "--project", "chats": "--root"}


def load_modules() -> list:
    if str(LIB) not in sys.path:
        sys.path.insert(0, str(LIB))
    modules = []
    for path in sorted(LIB.glob("*.py")):
        if path.stem.startswith("_"):
            continue
        try:
            modules.append(importlib.import_module(path.stem))
        except Exception as exc:  # noqa: BLE001  (one broken module must not break the whole CLI)
            print(f"agate: could not load {path.name}: {exc}", file=sys.stderr)
    return modules


def build(modules, root: Path) -> tuple[argparse.ArgumentParser, dict]:
    parser = argparse.ArgumentParser(prog="agate.py", description="Agate: one command for the project's base, "
                                     "extensions, skills, connectors, chats and exports.")
    parser.add_argument("--root", default=str(root), help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command", metavar="<command>")
    passthrough = {}
    for module in modules:
        if hasattr(module, "register"):
            module.register(sub, root)
        for name, help_ in getattr(module, "PASSTHROUGH", {}).items():
            sub.add_parser(name, help=help_ + f" (see `agate.py {name} --help`)", add_help=False)
            passthrough[name] = module
    return parser, passthrough


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    root = ROOT
    if len(argv) >= 2 and argv[0] == "--root":
        root, argv = Path(argv[1]).resolve(), argv[2:]
    modules = load_modules()
    parser, passthrough = build(modules, root)
    if argv and argv[0] in passthrough:
        name, rest = argv[0], argv[1:]
        flag = ROOT_FLAGS.get(name)
        if flag and flag not in rest:
            rest = [flag, str(root)] + rest
        sys.argv[0] = f"agate.py {name}"  # so its usage/help reads `agate.py <name> …`
        return passthrough[name].main(rest) or 0
    args = parser.parse_args(argv)
    args.root = str(root)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    return args.func(args) or 0
