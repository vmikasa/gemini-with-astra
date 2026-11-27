---
name: gemini-with-astra
description: Explicitly initialize, diagnose or upgrade a project for local Gemini–Codex collaboration on user request. Initialized projects use their resident rules. Ordinary tasks do not trigger initialization.
---

# gemini-with-astra · v0.2.1

Resolve script paths relative to this Skill. Requires Git and Python 3.9+ standard library. Use Python with -B to avoid bytecode files. Determine the active CLI host. Codex is ASTRA and Antigravity CLI (agy) is GEMINI, including after a model switch.

## Project setup

On explicit request only, inspect the intended Git root, existing rules and Git status. Choose private (rules and protocol may be committed) or local (excluded collaboration files). Ask if the mode is unclear. From the primary checkout use `python -B <skill>/scripts/setup.py init --root <repo> --mode private` or `--mode local`. Preserve user rules. For a local bridge explain the exact user-level paths and obtain separate consent before adding `--allow-global-bridge`. Never create a project, change global settings or launch a second CLI implicitly.

For diagnostics use `python -B <skill>/scripts/setup.py status --root <primary>`. Report static findings. Run the activation probe printed by the script in fresh CLI conversations in the same project; withhold the expected code. Discovery and natural-language behavior require actual CLI verification. Existing chat context cannot be reset by an upgrade.

## Existing projects

Replacing this Skill updates installed templates. A v0.1.1 project requires an explicit project upgrade. Run `python -B <skill>/scripts/upgrade.py --root <primary>` for a read-only preview. Identify drift and the backup location. After user approval and quiescing old writers, repeat with `--apply`. Back up and preserve old inboxes. Classifying a legacy entry under a task does not authorize delivery. An administrator can inspect selected entries and resolve them only after the user identifies exact recipients. Unknown entries remain Legacy Pending. See the protocol for scoped commands.

## After initialization

Each new CLI chat asks for L1 / L2 + task / L3 + predecessor unless already specified. Selection belongs to the current chat. Ordinary L1 work needs no session registration and never reads inboxes, including project broadcasts. Reopen or explicitly reread newly generated rules in already open chats. Use the copied project runtime and protocol for subsequent work.
