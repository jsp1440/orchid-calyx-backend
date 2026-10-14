"""Standalone FastAPI routes must not serve occurrence coordinates without auth.

``orchid_api.py`` was a runnable standalone app whose ``GET /api/occurrences``
returned raw database latitude/longitude with no authentication and a
wildcard CORS policy. Nothing imported or launched it, so it was removed.

This test keeps the class of defect from returning. For every tracked Python
file outside ``app/`` (which ``app.main`` mounts under its own auth
dependencies), it parses each FastAPI route handler. A handler that touches a
coordinate-like name (``decimal_latitude``, ``lat``, ``lng``, ``longitude``,
... in identifiers or string literals, including in module helpers it calls)
must actually depend on ``verify_owner_or_api_key``. That dependency can come
from the route decorator's ``dependencies=``, a ``Depends``/``Security``
parameter default, the app's own ``dependencies=``, or a local dependency
function that itself calls or depends on the owner check. A comment or an
unused import naming the check does not count.
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

from scripts.check_no_precise_coordinates import coordinate_axis

REPO_ROOT = Path(__file__).resolve().parent.parent

AUTH_CHECK = "verify_owner_or_api_key"
_ROUTE_METHODS = frozenset(
    {
        "get",
        "post",
        "put",
        "patch",
        "delete",
        "options",
        "head",
        "api_route",
        "websocket",
    }
)
_EXCLUDED_PREFIXES = ("app/", "tests/", "alembic/", "migrations/")
_WORDS = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _tracked_python_files() -> list[str]:
    output = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "-z", "--", "*.py"],
        check=True,
        capture_output=True,
    ).stdout
    return [
        entry.decode("utf-8", "surrogateescape")
        for entry in output.split(b"\0")
        if entry
    ]


def _callee_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _list_elements(call: ast.Call, keyword_name: str) -> list[ast.expr]:
    return [
        element
        for keyword in call.keywords
        if keyword.arg == keyword_name
        and isinstance(keyword.value, (ast.List, ast.Tuple))
        for element in keyword.value.elts
    ]


def _defaults(function: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.expr]:
    arguments = function.args
    return [
        default
        for default in [*arguments.defaults, *arguments.kw_defaults]
        if default is not None
    ]


class _Module:
    def __init__(self, tree: ast.Module) -> None:
        self.functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
        self.aliases: dict[str, ast.expr] = {}
        self.app_dependencies: dict[str, list[ast.expr]] = {}
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.functions[node.name] = node
            elif isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = node.targets[0]
                if not isinstance(target, ast.Name):
                    continue
                self.aliases[target.id] = node.value
                if isinstance(node.value, ast.Call) and _callee_name(
                    node.value.func
                ) in {"FastAPI", "APIRouter"}:
                    self.app_dependencies[target.id] = _list_elements(
                        node.value, "dependencies"
                    )

    def _dependency_target(self, node: ast.AST) -> ast.AST | None:
        """``Depends(x)``/``Security(x)`` -> ``x``; a module alias is followed."""

        if isinstance(node, ast.Name) and node.id in self.aliases:
            node = self.aliases[node.id]
        if (
            isinstance(node, ast.Call)
            and _callee_name(node.func) in {"Depends", "Security"}
            and node.args
        ):
            return node.args[0]
        return None

    def is_auth(self, node: ast.AST | None, depth: int = 0) -> bool:
        if node is None or depth > 4:
            return False
        name = _callee_name(node)
        if name == AUTH_CHECK:
            return True
        function = self.functions.get(name or "")
        if function is None:
            return False
        if any(
            self.is_auth(self._dependency_target(default), depth + 1)
            for default in _defaults(function)
        ):
            return True
        return any(
            isinstance(call, ast.Call) and self.is_auth(call.func, depth + 1)
            for call in ast.walk(function)
        )

    def depends_on_auth(self, node: ast.AST) -> bool:
        return self.is_auth(self._dependency_target(node))


def _touches_coordinates(
    function: ast.AST, module: _Module, seen: set[str] | None = None
) -> bool:
    seen = set() if seen is None else seen
    for node in ast.walk(function):
        words: list[str] = []
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            words = _WORDS.findall(node.value)
        elif isinstance(node, ast.Name):
            words = [node.id]
        elif isinstance(node, ast.Attribute):
            words = [node.attr]
        elif isinstance(node, (ast.keyword, ast.arg)):
            words = [getattr(node, "arg", None) or ""]
        if any(coordinate_axis(word) for word in words):
            return True
        if isinstance(node, ast.Call):
            callee = _callee_name(node.func)
            if callee in module.functions and callee not in seen:
                seen.add(callee)
                if _touches_coordinates(module.functions[callee], module, seen):
                    return True
    return False


def unauthenticated_coordinate_routes(source: str, filename: str) -> list[str]:
    module = _Module(ast.parse(source, filename=filename))
    offenders = []
    for function in module.functions.values():
        for decorator in function.decorator_list:
            if not (
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr in _ROUTE_METHODS
            ):
                continue
            if not _touches_coordinates(function, module):
                continue
            owner = _callee_name(decorator.func.value) or ""
            candidates: list[ast.AST] = [
                *module.app_dependencies.get(owner, []),
                *_list_elements(decorator, "dependencies"),
                *_defaults(function),
            ]
            if not any(module.depends_on_auth(candidate) for candidate in candidates):
                offenders.append(f"{filename}:{function.lineno} {function.name}")
    return offenders


def test_legacy_orchid_api_is_removed():
    assert "orchid_api.py" not in _tracked_python_files()
    assert not (REPO_ROOT / "orchid_api.py").exists()


def test_no_standalone_route_serves_coordinates_without_owner_check():
    offenders: list[str] = []
    for relative in _tracked_python_files():
        if relative.startswith(_EXCLUDED_PREFIXES):
            continue
        source = (REPO_ROOT / relative).read_text(encoding="utf-8", errors="replace")
        if "FastAPI" not in source and "APIRouter" not in source:
            continue
        try:
            offenders.extend(unauthenticated_coordinate_routes(source, relative))
        except SyntaxError:
            continue  # not importable, so not runnable as an app either
    assert offenders == []


def test_the_guarded_legacy_endpoint_is_recognised_as_guarded():
    source = (REPO_ROOT / "api_occurrence_points.py").read_text(encoding="utf-8")
    module = _Module(ast.parse(source))
    assert _touches_coordinates(module.functions["orchid_points"], module)
    assert unauthenticated_coordinate_routes(source, "api_occurrence_points.py") == []


_LEAKY = """
from fastapi import FastAPI
from app.security import verify_owner_or_api_key  # imported, never applied
app = FastAPI()

@app.get("/api/occurrences")
def points():
    return {"points": _rows()}

def _rows():
    return "SELECT decimal_latitude, decimal_longitude FROM oc_occurrences"
"""


def test_an_import_or_mention_of_the_check_is_not_enough():
    assert unauthenticated_coordinate_routes(_LEAKY, "leaky.py") == [
        "leaky.py:7 points"
    ]


def test_every_lat_lon_name_variant_counts_as_coordinates():
    for name in (
        "lat",
        "lng",
        "lon",
        "latitude",
        "longitude",
        "decimalLatitude",
        "site_lat",
    ):
        source = (
            "from fastapi import FastAPI\napp = FastAPI()\n"
            f"@app.get('/p')\ndef p(row):\n    return row.{name}\n"
        )
        assert unauthenticated_coordinate_routes(source, "v.py") == ["v.py:4 p"], name


def test_each_way_of_applying_the_check_is_recognised():
    guarded = {
        "decorator": (
            "from fastapi import Depends, FastAPI\napp = FastAPI()\n"
            "@app.get('/p', dependencies=[Depends(verify_owner_or_api_key)])\n"
            "def p():\n    return {'lat': 1}\n"
        ),
        "parameter": (
            "from fastapi import Depends, FastAPI\napp = FastAPI()\n"
            "@app.get('/p')\n"
            "async def p(identity=Depends(verify_owner_or_api_key)):\n"
            "    return {'lat': 1}\n"
        ),
        "app": (
            "from fastapi import Depends, FastAPI\n"
            "app = FastAPI(dependencies=[Depends(verify_owner_or_api_key)])\n"
            "@app.get('/p')\ndef p():\n    return {'lat': 1}\n"
        ),
        "wrapper": (
            "from fastapi import Depends, FastAPI, Security\napp = FastAPI()\n"
            "async def gate(request, key=Security(api_key_header)):\n"
            "    return await verify_owner_or_api_key(request, key)\n"
            "access = Depends(gate)\n"
            "@app.get('/p')\ndef p(identity=access):\n    return {'lat': 1}\n"
        ),
    }
    for way, source in guarded.items():
        assert unauthenticated_coordinate_routes(source, "g.py") == [], way


def test_a_wrapper_that_does_not_call_the_check_is_not_auth():
    source = (
        "from fastapi import Depends, FastAPI\napp = FastAPI()\n"
        "def gate():\n    return True  # verify_owner_or_api_key TODO\n"
        "@app.get('/p')\ndef p(identity=Depends(gate)):\n    return {'lng': 1}\n"
    )
    assert unauthenticated_coordinate_routes(source, "w.py") == ["w.py:6 p"]
