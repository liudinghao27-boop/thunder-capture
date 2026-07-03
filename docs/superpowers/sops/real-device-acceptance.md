# Real Device Acceptance SOP

## Preconditions

1. Use a dedicated sender phone and a dedicated receiver account. Never use customer leads.
2. Enable USB debugging and confirm the computer authorization dialog.
3. Put the phone on the exact receiver profile before a live-send run.
4. Confirm `adb devices -l` reports the device as `device`, not `offline` or `unauthorized`.

## Dry Run

The dry run may install and select `ADBKeyboard.apk`. It captures health, keyboard state,
screenshot, OCR, UI hierarchy, inferred screen and the planned action. It performs no phone
navigation and no send action.

```powershell
python scripts/smoke/real_device_acceptance.py `
  --serial DEVICE_SERIAL `
  --industry INDUSTRY_SLUG `
  --target QA_RECEIVER `
  --message "验收测试，请忽略" `
  --dry-run
```

Evidence is written to `data/acceptance/<correlation_id>/`. Do not proceed unless the report
status is `dry_run_ready`, the target device and screen are correct, and no blocker is present.

## Guarded Live Send

All three live-send controls are mandatory. The target must exactly equal one visible profile
identifier on the current screen; substring matches are rejected. The send limit must be one.

```powershell
python scripts/smoke/real_device_acceptance.py `
  --serial DEVICE_SERIAL `
  --industry INDUSTRY_SLUG `
  --target QA_RECEIVER `
  --message "验收测试，请忽略" `
  --live-send `
  --confirm-target QA_RECEIVER `
  --max-sends 1
```

Verify the receiver account contains exactly one message. A task is successful only when the
post-send screenshot/OCR/UI evidence confirms the sent message. `unconfirmed_send` is a failure.

## Required Evidence

- `correlation_id`, `job_id`, `device_id`, `task_id`, and `claim_token`
- Device model, Android version, battery, boot and ADB Keyboard state
- Before/after screenshots, OCR status and UI elements
- Inferred screen, confidence, blocker and send verification reason
- Final report and JSONL event log

## Stop Conditions

Stop immediately on a wrong profile, captcha, login request, real-name verification, risk control,
device disconnect, keyboard error, duplicate message, or any target mismatch. Do not retry a live
send until the evidence has been reviewed.
