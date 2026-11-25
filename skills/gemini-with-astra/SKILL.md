---
name: gemini-with-astra
description: Initializes or diagnoses the persistent Gemini–Codex dual-agent collaboration environment ONLY on explicit user request to initialize or diagnose gemini-with-astra. Never initialize merely because a task involves another agent, planning, review, or handoff. Once initialized, use the project's resident rules instead of invoking this skill for everyday work.
---

# gemini-with-astra · v0.1.1

## Goal
Install a persistent, project-local collaboration contract. The user can then talk naturally to either CLI; ordinary tasks need no skill invocation, formal ticket, or mandatory second-agent review.

## Before writing
- This skill may modify a project only when the user explicitly asks to initialize it. For implicit discovery, unrelated requests, or a status request, do not initialize. Never change global rules without explicit, separate permission.
- Identify the intended Git root (use `git rev-parse --show-toplevel`); inspect existing instructions, current Git status and any prior collaboration state. Do not create a Git repository, commit, stash, or reset implicitly.
- Establish storage mode once: `private` = versionable project rules, spec and protocol; `local` = no tracked repository modifications. If unclear whether the user owns the repository or wants local-only rules, ask this one question. Do not guess ownership from the presence of a remote.
- Use the bundled `scripts/setup.py` with an absolute path resolved relative to this SKILL.md, not relative to the target repo. Requires Python 3.9+ and Git. Windows: `py -3` or `python`; other platforms: `python3`. The script performs preflight checks and never installs dependencies.

## Initialize
Run `python <skill-dir>/scripts/setup.py init --root <repo-root> --mode private|local` (choose exactly one mode). The script is additive, refuses unsafe collisions, preserves existing project content, and is safe to rerun. Do not improvise around a refusal or overwrite user rules. If a local-only repo already has a root rule or override, the script requires explicit consent for the exact-root global bridge: explain which user-level files would change, then only with consent repeat with `--allow-global-bridge`. The bridge is not a permissions change. No global changes by default.

The script copies the runtime protocol and a read-only snapshot helper into the project, so daily collaboration does not depend on the skill remaining installed. `SPEC.md` and `DECISIONS.md` are intentionally not pre-created: create them only when approved design or durable decisions actually exist. Read the generated resident rule in this current session; startup discovery may be stale. Existing project conventions still apply. Never invent a spec or promote discussion into approval. Preserve existing spec and decision files.

## Done when
- Run `python <skill-dir>/scripts/setup.py status --root <repo-root>` and report the static result, exact locations and any conflicts. No staging/committing is required. In local mode verify no new tracked changes and the generated local paths are excluded.
- Give the user the one-time fresh-session probe from the script output. Run it in *both* Codex and agy, from the same root, without calling this skill. Check the activation code and trigger explanation. If the user cannot run both now, report `INITIALIZED / CLI ACTIVATION UNVERIFIED`; never claim active in both just because files exist. A static PASS does not prove discovery. If one fails, investigate instructions, precedence, size cap, cwd, profile, trust and permissions; keep working in the verified CLI or explicitly read the resident rule as a temporary fallback.
- For a diagnostic request, use `status` only. For repeat initialization, preserve files; report drift rather than overwriting. Do not automatically activate on other repositories, switch models, launch another CLI, or build an orchestration service.

After initialization, the persistent rule is the entry point. Use natural language; no further `$gemini-with-astra` or `/gemini-with-astra` calls are needed for tasks, review, exploration, or sync.
