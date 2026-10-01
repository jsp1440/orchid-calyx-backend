import base64
import importlib.util
import json
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "edith_app_checks.py"
_spec = importlib.util.spec_from_file_location("edith_app_checks", _PATH)
checks = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(checks)


def _jwt(claims: dict) -> str:
    def part(obj: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")

    return f"{part({'alg': 'HS256', 'typ': 'JWT'})}.{part(claims)}.c2lnbmF0dXJlLXNpZ25hdHVyZQ"


def test_anon_key_is_recorded_and_not_privileged():
    roles = checks.jwt_roles(f"const k='{_jwt({'role': 'anon', 'projectId': 'x'})}';")
    assert [r[1] for r in roles] == ["anon"]
    assert "..." in roles[0][0]  # token is redacted in evidence


def test_service_role_key_is_detected():
    text = f"a='{_jwt({'role': 'anon'})}';b=\"{_jwt({'role': 'service_role'})}\""
    assert sorted(r[1] for r in checks.jwt_roles(text)) == ["anon", "service_role"]


def test_prose_excludes_code_and_utility_classes():
    text = (
        "x('Edith asks the reader what they actually see on the roots today');"
        "y(\" && data && !data.found && <p className=\");"
        "z('rounded-lg border px-5 py-10 shadow-[0_10px_40px] sm:px-10 sm:py-14 text-lg');"
    )
    assert checks.prose(text) == {"edith asks the reader what they actually see on the roots today"}


def test_decode_escapes_restores_minified_unicode():
    assert checks.decode_escapes("Edith\\u2019s \\u{1F33F}") == "Edith’s \U0001F33F"


def test_failed_gate_carries_blocker_and_passing_gate_does_not():
    assert checks.gate("app_build", "FAIL", "exit 1", blocker="b", action="a")["blocker"] == "b"
    passing = checks.gate("app_build", "PASS", "exit 0", blocker="b", action="a")
    assert passing["blocker"] is None and passing["smallest_next_action"] is None


def test_lint_errors_keep_errors_with_their_files_and_drop_warnings():
    out = (
        "/home/runner/work/_temp/edith-app/app/src/components/ui/sidebar.tsx\n"
        "  733:3  warning  Fast refresh only works when a file only exports components  react-refresh/only-export-components\n"
        "/home/runner/work/_temp/edith-app/app/src/lib/content.ts\n"
        "  12:7  error  'x' is assigned a value but never used  @typescript-eslint/no-unused-vars\n"
    )
    assert checks.lint_errors(out) == [
        "lib/content.ts 12:7 error 'x' is assigned a value but never used @typescript-eslint/no-unused-vars"
    ]
