#!/usr/bin/env python3
"""List the environment variable names ``app/`` reads, by static analysis.

Parses every module under ``app/`` (it imports nothing from them) and records
each read of the process environment:

* ``os.getenv(K)``, ``os.environ.get(K)``, ``os.environ[K]``, ``K in os.environ``
  and ``os.environ.setdefault/pop(K)``;
* the same calls on a mapping that stands in for ``os.environ`` (a name or
  attribute called ``environ``, ``env``, ``source``, ``e`` or ``self.env``),
  which is how the repository's ``from_environ(environ=None)`` helpers read it.

The key ``K`` is resolved when it is a string literal, a module- or
function-level string constant, a loop/comprehension variable over a tuple of
those, or a parameter of a helper whose same-module callers pass literals
(``_env_first("A", "B")``, ``flag("NAME", "false")``). A read whose key cannot
be resolved is reported as a site (``path:function``), never guessed.

``--json`` prints ``{"names": {...}, "unresolved": [...]}``; the default
prints one name per line.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_NAME = re.compile(r"[A-Z][A-Z0-9_]*")
MAPPING_NAMES = frozenset({"environ", "env", "source", "e", "environment"})
SELF_MAPPING_NAMES = MAPPING_NAMES | {"_env", "_environ"}
# Accessors returning the environment mapping, e.g. ``self._environ().get(K)``.
MAPPING_ACCESSORS = frozenset({"_environ", "environ", "_env"})
# Module constants named ``*_ENV`` hold an environment variable's name by
# repository convention; they count as read even when the read is indirect.
ENV_CONSTANT = re.compile(r"_?[A-Z0-9_]*_ENV")
READ_METHODS = frozenset({"get", "setdefault", "pop"})


def _is_os_environ(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "environ"
        and isinstance(node.value, ast.Name)
        and node.value.id == "os"
    )


def _is_env_mapping(node: ast.AST) -> bool:
    if _is_os_environ(node):
        return True
    if isinstance(node, ast.Name):
        return node.id in MAPPING_NAMES
    if isinstance(node, ast.Call) and not node.args:
        func = node.func
        name = (
            func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        )
        return name in MAPPING_ACCESSORS
    return (
        isinstance(node, ast.Attribute)
        and node.attr in SELF_MAPPING_NAMES
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
    )


def _strings(node: ast.AST | None) -> list[str] | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.Tuple | ast.List | ast.Set):
        out: list[str] = []
        for item in node.elts:
            values = _strings(item)
            if values is None:
                return None
            out.extend(values)
        return out
    return None


class _Module:
    def __init__(self, path: Path, tree: ast.Module) -> None:
        self.path = path
        self.tree = tree
        self.constants: dict[str, list[str]] = {}
        for node in tree.body:
            targets = []
            if isinstance(node, ast.Assign):
                targets, value = node.targets, node.value
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                targets, value = [node.target], node.value
            for target in targets:
                if isinstance(target, ast.Name):
                    values = _strings(value)
                    if values is not None:
                        self.constants[target.id] = values
        self.parents: dict[ast.AST, ast.AST] = {}
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                self.parents[child] = parent
        self.functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {
            node.name: node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        }

    def enclosing_function(self, node: ast.AST):
        while node in self.parents:
            node = self.parents[node]
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                return node
        return None

    def resolve(self, node: ast.AST, at: ast.AST, depth: int = 0) -> list[str] | None:
        values = _strings(node)
        if values is not None:
            return values
        if isinstance(node, ast.Starred):
            return self.resolve(node.value, at, depth)
        if not isinstance(node, ast.Name) or depth > 3:
            return None
        name = node.id
        scope = at
        while scope in self.parents:
            scope = self.parents[scope]
            bound = self._bound_in(scope, name, at, depth)
            if bound is not None:
                return bound
            if isinstance(scope, ast.FunctionDef | ast.AsyncFunctionDef):
                param = self._param(scope, name, depth)
                if param is not None:
                    return param
        return self.constants.get(name)

    def _bound_in(self, scope: ast.AST, name: str, at: ast.AST, depth: int):
        for node in ast.walk(scope):
            if (
                isinstance(node, ast.For | ast.comprehension)
                and isinstance(node.target, ast.Name)
                and node.target.id == name
            ):
                return self.resolve(node.iter, node.iter, depth + 1)
            if isinstance(node, ast.Assign) and node is not at:
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == name:
                        values = _strings(node.value)
                        if values is not None:
                            return values
        return None

    def _param(self, function, name: str, depth: int) -> list[str] | None:
        args = function.args
        positional = [a.arg for a in (*args.posonlyargs, *args.args)]
        is_star = args.vararg is not None and args.vararg.arg == name
        keyword_only = [a.arg for a in args.kwonlyargs]
        if name not in positional and name not in keyword_only and not is_star:
            return None
        found: list[str] = []
        calls = 0
        for node in ast.walk(self.tree):
            if not (isinstance(node, ast.Call) and _callee(node) == function.name):
                continue
            calls += 1
            if is_star:
                candidates = node.args[len(positional) :]
            else:
                candidates = [k.value for k in node.keywords if k.arg == name]
                if name in positional:
                    index = positional.index(name)
                    if len(node.args) > index:
                        candidates.append(node.args[index])
            for arg in candidates:
                values = self.resolve(arg, node, depth + 1)
                if values is None:
                    return None
                found.extend(values)
        return found if calls and found else None


def _callee(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _read_keys(node: ast.AST) -> list[ast.AST]:
    """The key expressions of every environment read at ``node``."""

    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        func = node.func
        if (
            func.attr == "getenv"
            and isinstance(func.value, ast.Name)
            and func.value.id == "os"
        ):
            return node.args[:1]
        if func.attr in READ_METHODS and _is_env_mapping(func.value) and node.args:
            return node.args[:1]
    if isinstance(node, ast.Subscript) and _is_env_mapping(node.value):
        return [node.slice]
    if (
        isinstance(node, ast.Compare)
        and any(isinstance(op, ast.In | ast.NotIn) for op in node.ops)
        and any(_is_env_mapping(c) for c in node.comparators)
    ):
        return [node.left]
    return []


def env_reads(root: Path = ROOT) -> tuple[dict[str, list[str]], list[str]]:
    """``({name: [path, ...]}, [unresolved "path:function", ...])`` for app/."""

    names: dict[str, set[str]] = defaultdict(set)
    unresolved: set[str] = set()
    for path in sorted((root / "app").rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        module = _Module(path, tree)
        for constant, values in module.constants.items():
            if (
                ENV_CONSTANT.fullmatch(constant)
                and len(values) == 1
                and ENV_NAME.fullmatch(values[0])
            ):
                names[values[0]].add(relative)
        for node in ast.walk(tree):
            for key in _read_keys(node):
                values = module.resolve(key, node)
                if values is None:
                    function = module.enclosing_function(node)
                    unresolved.add(
                        f"{relative}:{function.name if function else '<module>'}"
                    )
                    continue
                for value in values:
                    if ENV_NAME.fullmatch(value):
                        names[value].add(relative)
    return {k: sorted(v) for k, v in sorted(names.items())}, sorted(unresolved)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    names, unresolved = env_reads()
    if args.json:
        print(json.dumps({"names": names, "unresolved": unresolved}, indent=2))
    else:
        print("\n".join(names))
    return 0


if __name__ == "__main__":
    sys.exit(main())
