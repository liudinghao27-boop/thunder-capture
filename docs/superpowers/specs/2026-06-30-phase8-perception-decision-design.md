# Phase 8 Perception Decision Design

## Objective

Upgrade device execution from "send command and trust result" to an evidence-driven Agent loop:

1. Capture screenshot at key steps.
2. Extract OCR text from the screenshot.
3. Parse Android UI hierarchy.
4. Infer page state and blockers.
5. Convert observation into an explicit Agent decision.
6. Persist evidence for logs, debugging, retry, and Web UI display.

## Decision Contract

Every key observation must be convertible into:

```json
{
  "page_state": "chat_input_ready",
  "confidence": 0.92,
  "next_action": "input_message",
  "reason": "Chat input is visible and ready for message entry.",
  "screenshot": "..."
}
```

Extended fields are allowed when they help auditability:

- `blocker`: normalized blocker code such as `risk_control`, `login_required`, `captcha`, `dm_unavailable`.
- `evidence`: UI/OCR/state evidence used by the parser.
- `ocr_text`: OCR text captured from the current screenshot.
- `ui_elements`: parsed Android UI elements.

## State Mapping

| Observation screen | Blocker | Decision page_state | next_action |
| --- | --- | --- | --- |
| `chat` | empty | `chat_input_ready` | `input_message` |
| `message_sent` | empty | `message_sent` | `confirm_success` |
| `profile` | empty | `profile` | `open_chat` |
| `search` | empty | `search` | `search_target` |
| `launcher` | empty | `launcher` | `open_app` |
| any | non-empty | `blocked` | `stop` |
| `unknown` | empty | `unknown` | `observe` |

## Runner Integration

`TaskGraphRunner` records decisions at:

- `before_execute`: decide whether execution can proceed.
- `after_execute`: verify send result and decide whether success is confirmed.

Blocked preflight must skip phone action and return the decision in `ExecutionResult.payload["decision"]`.

Post-send results must include:

```json
{
  "send_verification": {},
  "agent_decisions": {
    "before": {},
    "after": {}
  }
}
```

## Evidence Requirements

Failure and blocker states must preserve:

- screenshot path
- OCR text
- UI evidence
- parser confidence
- normalized blocker
- decision reason

This gives the operator enough context to diagnose whether the issue is UI drift, OCR failure, login expiry, platform risk control, or send verification failure.
