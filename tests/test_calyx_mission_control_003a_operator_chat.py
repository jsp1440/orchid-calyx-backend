import pytest

from runtime.operator_chat import GovernedOperatorChat


def test_chat_records_operator_and_calyx_messages():
    chat = GovernedOperatorChat()
    operator = chat.receive("What are you working on?", created_at="2026-08-02T06:00:00Z")
    reply = chat.reply("I am validating the governed cycle.", created_at="2026-08-02T06:00:01Z")
    transcript = chat.transcript()
    assert transcript == (operator, reply)
    assert operator.role == "operator"
    assert reply.requires_approval is False


def test_action_proposals_require_approval():
    chat = GovernedOperatorChat()
    reply = chat.reply(
        "I prepared a draft pull request.",
        proposed_action="create-draft-pr",
        created_at="2026-08-02T06:00:00Z",
    )
    assert reply.requires_approval is True


def test_prohibited_actions_never_become_automatic():
    chat = GovernedOperatorChat()
    for action in chat.prohibited_actions:
        reply = chat.reply(
            f"Proposed action: {action}",
            proposed_action=action,
            created_at=f"2026-08-02T06:00:{len(chat.transcript()):02d}Z",
        )
        assert reply.requires_approval is True
    status = chat.status()
    assert status["automatic_merge"] is False
    assert status["automatic_deploy"] is False
    assert status["automatic_publication"] is False
    assert status["external_communication"] is False


def test_empty_messages_fail_closed():
    chat = GovernedOperatorChat()
    with pytest.raises(ValueError):
        chat.receive("   ")
    with pytest.raises(ValueError):
        chat.reply("")
