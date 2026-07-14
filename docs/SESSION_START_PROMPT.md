# Mandatory Session Start Prompt

Paste this at the start of every new ChatGPT or Codex session working on DayForge:

```text
Project: DayForge — Forge Better Trading Every Day
Repository: zahirulca24-bit/DayForge-Forge-Better-Trading-Every-Day

Before giving an opinion or changing code:

1. Read PROJECT_CONTROL.md.
2. Read docs/DECISION_LOG.md.
3. Read docs/TASK_REGISTER.md.
4. Read docs/EVIDENCE_REGISTER.md.
5. Read docs/HANDOFF.md.
6. Read the current task's issue and open PR, if any.
7. Inspect actual code on the named branch/commit.

Rules:

- Repository control files are project memory; chat memory is not project truth.
- Do not silently change a LOCKED decision.
- Claim exactly one task.
- Use one task, one branch and one PR.
- Do not merge to main without explicit Product Owner approval.
- Do not start, stop, pause or resume the bot without explicit Product Owner approval.
- Separate CODE PASS, CI PASS, RUNTIME PASS and VERIFIED COMPLETE.
- Screenshots prove observations, not automatic root cause.
- State facts and inferences separately.
- When evidence conflicts, stop and report the contradiction before changing code.
- Update TASK_REGISTER, EVIDENCE_REGISTER and HANDOFF before ending the session.

First response must report only:

A. Current main/deployed truth
B. Current active task and owner
C. Locked decisions relevant to the task
D. Confirmed evidence
E. Contradictions/blockers
F. Exact bounded action proposed

Do not begin implementation when another task is already active unless the Product Owner explicitly pauses or replaces it.
```

## Compact emergency handoff prompt

When a chat must be changed quickly:

```text
Read PROJECT_CONTROL.md and docs/HANDOFF.md first. Continue only the active task in docs/TASK_REGISTER.md. Do not revise locked decisions, start another task, change the bot's runtime state or merge any PR without Product Owner approval. Verify every claim against docs/EVIDENCE_REGISTER.md and actual code.
```
