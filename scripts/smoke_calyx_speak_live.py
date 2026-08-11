"""Authenticated live acceptance test for server-owned Speak with Calyx.

This script is read/reason only: it creates a conversation and Brain missions, but it
never approves, publishes, promotes Candidate Knowledge, mutates taxonomy, or writes the
Knowledge Graph. It is intended to run inside the protected production GitHub
environment so owner credentials never leave GitHub Actions.
"""

from __future__ import annotations

import json
import os
import sys
from http.cookiejar import CookieJar
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener

BASE_URL = os.environ.get(
    "CALYX_BACKEND_URL", "https://orchid-calyx-backend.onrender.com"
).strip().rstrip("/")
ACCESS_CODE = os.environ.get("CALYX_OWNER_ACCESS_CODE", "")
SUPPORTED_SPEAK_RELEASES = {
    "CALYX-SPEAK-004-CONTEXT",
    "CALYX-SPEAK-005-WORKSPACE-OUTPUTS",
}

QUESTIONS = [
    "Hello Calyx. What are you able to help me with?",
    (
        "We are designing Calyx Vision. What visual information would you need encoded "
        "in glossary illustrations so you can later reason reliably from orchid "
        "photographs, herbarium specimens, and botanical illustrations?"
    ),
    (
        "Why do you need that information, and which requirements are essential versus "
        "merely useful?"
    ),
    (
        "Which of your recommendations come from canonical Orchid Continuum architecture, "
        "which come from scientific evidence, and which are your design inferences?"
    ),
    (
        "Given the rest of the Orchid Continuum architecture, what information would you "
        "wish had been encoded into these glossary illustrations now, before hundreds of "
        "them are generated?"
    ),
]

COOKIE_JAR = CookieJar()
OPENER = build_opener(HTTPCookieProcessor(COOKIE_JAR))


def request(
    path: str,
    *,
    method: str = "GET",
    payload: dict | None = None,
) -> tuple[int, dict]:
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    req = Request(f"{BASE_URL}{path}", data=data, headers=headers, method=method)
    with OPENER.open(req, timeout=90) as response:
        body = response.read().decode()
        return response.status, json.loads(body) if body else {}


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    if not ACCESS_CODE:
        return fail("CALYX_OWNER_ACCESS_CODE is not available in the production environment")

    try:
        status, health = request("/health")
        if status != 200:
            return fail(f"health returned {status}")
        print(f"PASS health: {status} {health}")

        status, session = request(
            "/api/mission-control/owner/session",
            method="POST",
            payload={"access_code": ACCESS_CODE},
        )
        if status != 200:
            return fail(f"owner authentication returned {status}")
        if not list(COOKIE_JAR):
            return fail("owner authentication returned no session cookie")
        print(
            "PASS owner authentication via HttpOnly cookie "
            f"mode={session.get('token') or session.get('access_token') or 'cookie'}"
        )

        try:
            status, speak_status = request("/api/calyx/speak/status")
        except HTTPError as exc:
            if exc.code == 404:
                return fail("deployed Speak status route is not available")
            raise
        release = str(speak_status.get("release") or "")
        if status != 200 or release not in SUPPORTED_SPEAK_RELEASES:
            supported = ", ".join(sorted(SUPPORTED_SPEAK_RELEASES))
            return fail(
                f"deployed Speak release mismatch: expected one of [{supported}], got {release or status}"
            )
        print(
            "PASS deployed Speak release: "
            f"{release} degraded_retrieval={speak_status.get('semantic_retrieval_degraded_mode')}"
        )

        readiness = speak_status.get("reply_provider")
        if isinstance(readiness, dict):
            print(
                "PROVIDER READINESS: "
                f"mode={readiness.get('mode')} "
                f"model={readiness.get('model')} "
                f"generative_configured={readiness.get('generative_configured')} "
                f"live_acceptance_verified={readiness.get('live_acceptance_verified')}"
            )
            if readiness.get("generative_configured") is False:
                return fail(
                    "Speak status reports deterministic/non-generative provider mode; "
                    "do not consume the Vision acceptance dialogue until a generative provider is configured"
                )

        status, conversation = request(
            "/api/calyx/speak/conversations",
            method="POST",
            payload={
                "title": "CALYX-SPEAK live acceptance — Vision requirements",
                "project_id": "calyx-vision-live-acceptance",
                "context": {
                    "purpose": "live acceptance and Calyx Vision requirements review",
                    "publication_authority": False,
                    "knowledge_graph_write_authority": False,
                },
            },
        )
        if status != 201 or not conversation.get("conversation_id"):
            return fail(f"conversation creation returned {status}: {conversation}")
        conversation_id = conversation["conversation_id"]
        print(
            "PASS conversation created: "
            f"{conversation_id} persistence={conversation.get('persistence_mode')}"
        )

        provider_names: list[str] = []
        provider_models: list[str] = []
        answers: list[str] = []
        for index, question in enumerate(QUESTIONS, start=1):
            status, turn = request(
                f"/api/calyx/speak/conversations/{conversation_id}/turns",
                method="POST",
                payload={
                    "message": question,
                    "project_id": "calyx-vision-live-acceptance",
                    "research_mode": "auto" if index == 1 else "always",
                    "retrieval_limit": 12,
                    "context": {"acceptance_turn": index},
                },
            )
            if status != 200:
                return fail(f"turn {index} returned {status}: {turn}")
            answer = str(turn.get("answer") or "").strip()
            provider = turn.get("provider") or {}
            provider_name = str(provider.get("name") or "")
            provider_model = str(provider.get("model") or "")
            if not answer:
                return fail(f"turn {index} returned an empty Calyx answer")
            if not provider_name:
                return fail(f"turn {index} omitted provider identity")
            provider_names.append(provider_name)
            provider_models.append(provider_model)
            answers.append(answer)
            print(f"\n===== CALYX TURN {index} =====")
            print(f"QUESTION: {question}")
            print(f"PROVIDER: {provider_name} / {provider_model}")
            research = turn.get("research") or {}
            mission = research.get("mission") or {}
            retrieval = research.get("retrieval") or {}
            print(
                "RETRIEVAL: "
                f"status={retrieval.get('status')} error={retrieval.get('error', 'none')}"
            )
            print(
                "MISSION: "
                f"{mission.get('mission_id', 'none')} "
                f"state={mission.get('state', 'none')} "
                f"review={mission.get('review_status', 'none')}"
            )
            print("ANSWER:")
            print(answer)

        status, restored = request(
            f"/api/calyx/speak/conversations/{conversation_id}"
        )
        if status != 200:
            return fail(f"conversation restore returned {status}")
        messages = restored.get("messages") or []
        if len(messages) < len(QUESTIONS) * 2:
            return fail(
                f"server transcript did not persist enough messages: {len(messages)}"
            )
        print(f"PASS server transcript restored with {len(messages)} messages")

        if any(name == "deterministic-governed" for name in provider_names[1:]):
            return fail(
                "substantive Vision turns used deterministic-governed fallback; "
                "configure CALYX_CHAT_COMPLETIONS_URL and CALYX_CHAT_MODEL before "
                "claiming conversational-scientific acceptance"
            )
        substantive_models = {model for model in provider_models[1:] if model}
        if len(substantive_models) != 1:
            return fail(
                "substantive Vision turns did not use one stable reported provider model: "
                f"{sorted(substantive_models)}"
            )

        combined = " ".join(answers[1:]).casefold()
        expected_markers = ("evidence", "inference", "visual")
        missing = [marker for marker in expected_markers if marker not in combined]
        if missing:
            return fail(
                "Vision requirements dialogue did not expose expected epistemic/visual "
                f"content markers: {missing}"
            )

        print(
            "PASS live multi-turn Calyx Vision requirements acceptance "
            f"release={release} model={next(iter(substantive_models))}"
        )
        return 0
    except HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        return fail(f"HTTP {exc.code} from deployed backend: {detail[:1000]}")
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        return fail(f"deployed backend request failed: {exc!r}")


if __name__ == "__main__":
    sys.exit(main())
