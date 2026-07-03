from argparse import Namespace

import pytest

from scripts.smoke.real_device_acceptance import (
    observed_profile_matches,
    summarize_acceptance_evidence,
    validate_live_send,
)


def _args(**overrides):
    values = {
        "live_send": True,
        "target": "qa_receiver",
        "confirm_target": "qa_receiver",
        "max_sends": 1,
    }
    values.update(overrides)
    return Namespace(**values)


def test_profile_match_requires_an_exact_visible_identifier():
    elements = [{"text": "qa_receiver"}, {"content_desc": "私信"}]
    assert observed_profile_matches("qa_receiver", elements, "")
    assert not observed_profile_matches("qa_receive", elements, "")
    assert not observed_profile_matches("receiver", elements, "用户 qa_receiver 的主页")


def test_live_send_requires_exact_confirmation_and_single_send_limit():
    with pytest.raises(ValueError, match="confirm-target"):
        validate_live_send(_args(confirm_target="someone_else"), profile_matches=True)
    with pytest.raises(ValueError, match="max-sends"):
        validate_live_send(_args(max_sends=2), profile_matches=True)


def test_live_send_refuses_when_observed_profile_does_not_match():
    with pytest.raises(ValueError, match="observed profile"):
        validate_live_send(_args(), profile_matches=False)


def test_valid_guarded_live_send_is_accepted():
    validate_live_send(_args(), profile_matches=True)


def test_summarize_acceptance_evidence_includes_dry_run_before_decision():
    observation = {
        "screen": "profile_dm_ready",
        "confidence": 0.91,
        "blocker": "",
        "screenshot_path": "data/acceptance/before.png",
        "evidence": ["profile dm button"],
        "ocr_text": "qa_receiver",
        "elements": [{"text": "Message"}],
    }

    evidence = summarize_acceptance_evidence(observation=observation)

    assert evidence["before_decision"]["page_state"] == "profile_dm_ready"
    assert evidence["before_decision"]["next_action"] == "open_chat"
    assert evidence["after_decision"] == {}
    assert evidence["send_verification"] == {}
    assert evidence["screenshot_path"] == "data/acceptance/before.png"


def test_summarize_acceptance_evidence_prefers_live_result_decisions():
    observation = {
        "screen": "profile",
        "confidence": 0.5,
        "screenshot_path": "data/acceptance/initial.png",
    }
    result = {
        "action_result": {
            "payload": {
                "agent_decisions": {
                    "before": {
                        "page_state": "profile_dm_ready",
                        "next_action": "open_chat",
                        "screenshot": "data/acceptance/before.png",
                    },
                    "after": {
                        "page_state": "message_sent",
                        "next_action": "confirm_success",
                        "screenshot": "data/acceptance/after.png",
                    },
                },
                "send_verification": {
                    "ok": True,
                    "reason": "message_visible",
                    "screenshot_path": "data/acceptance/after.png",
                },
            }
        }
    }

    evidence = summarize_acceptance_evidence(observation=observation, result=result)

    assert evidence["before_decision"]["page_state"] == "profile_dm_ready"
    assert evidence["after_decision"]["next_action"] == "confirm_success"
    assert evidence["send_verification"]["reason"] == "message_visible"
    assert evidence["screenshot_path"] == "data/acceptance/after.png"
