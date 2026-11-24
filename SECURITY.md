# Security

## Permissions

Each tool has a risk class, and you choose a trust level. Both are defined in `jarvis_os/safety/policy.py`.

| Risk | Examples |
|---|---|
| READ | read email, screenshot, search, recall |
| PREPARE | drafts, notes, memories, tasks (private to you) |
| LOCAL | click/type, open apps, move files, archive email (reversible) |
| EXTERNAL | send email, calendar invites (other people see it) |
| DANGEROUS | delete (Recycle Bin), change permissions/settings |

| Trust level | What it allows |
|---|---|
| 0 Observe | READ only |
| 1 Suggest | + PREPARE |
| **2 Execute with approval (default)** | + LOCAL. EXTERNAL and DANGEROUS ask first |
| 3 Trusted | EXTERNAL is automatic for tools listed in `trusted_tools` |
| 4 Autonomous | EXTERNAL is automatic. DANGEROUS still asks |

Approvals are answered by voice ("yes" / "no") or with the on-screen card, whichever comes first. If there's no answer within `approval_timeout` (45 s), the action is **denied**. Every decision goes into the `approvals` table.

## Prompt injection
Email, file and web content reaches the model wrapped in `<untrusted_content>` tags (`wrap_untrusted`). Text inside those tags that tries to close the tag early is neutralized. The system prompt treats such content as data, never as instructions. The mock inbox contains an injection attempt, and the tests check that it stays wrapped.

## Files
File tools are confined to `settings.file_roots` (your Desktop, Documents, Downloads, Pictures, Music and Videos folders). A path containing `..` that escapes those folders is rejected. JARVIS never overwrites existing files. Deleting sends files to the Recycle Bin, and only with approval.

## Computer control
Moving the mouse into a screen corner stops all automation instantly (pyautogui FAILSAFE). The agent has to observe the screen before acting and verify afterwards, and it must not type into existing documents unless you asked it to.

## Secrets
- `.env`, `credentials.json` and `token.json` stay on this PC. Never commit or share them.
- The Claude login is handled by Claude Code. JARVIS removes any `ANTHROPIC_API_KEY` from its environment, so no key gets used by accident.
- Arguments named like passwords, secrets, tokens, API keys or credentials are replaced with `***` in the activity log, and stored results are truncated.
- JARVIS has no shell or code-execution tool. Claude's built-in file and Bash tools are switched off (`tools=["WebSearch","WebFetch"]`), and your Claude Code settings aren't loaded (`setting_sources=[]`).

## Privacy mode
Say "privacy mode". The microphone stream is dropped before any processing, nothing new is stored in memory, and the orb turns violet. To resume, press the hotkey or click the orb.

## Not done yet
- Encryption of `token.json` with Windows DPAPI
- Per-tool rate limits
- Sandboxed code execution (there's no code tool at all)
