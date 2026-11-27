# Dual collaboration protocol · v0.2.0

This is a project runtime reference, not a second set of mandatory instructions. Read only the relevant section. The resident rule defines triggers. All paths are relative to the actual repository root. Astra = Codex side (including other Codex models); Gemini = agy side. If side or intended task is genuinely ambiguous, ask once rather than guess.

## 1. Shared facts and decisions

- Specification: `@SPEC@`. Create it only when the first user-approved baseline is worth preserving. Record confirmed goals, user experience intent, hard constraints, public contracts and major architecture; leave internal implementation choices open. If absent, treat the project spec as not yet established; do not create an empty placeholder.
- Decision log: `@DECISIONS@`. Create it only when the first consequential decision is confirmed. Record date, decision, reason, alternatives/tradeoff, approval source and affected spec/tasks. If a confirmed decision changes the current baseline, update the spec too. Pending suggestions remain proposals; never silently promote them. A user-approved direct request can change a design; preserve the approval context.
- Code, Git and observed tests describe actual implementation. They may contradict the intended spec. Investigate discrepancies rather than silently rewriting intent or reverting code. Re-read relevant files after material changes or a resumed session.
- The primary checkout's ignored `.ai/` stores local collaboration state, including open sessions and unresolved deliveries. Back it up when moving a project. A fresh Git clone will not contain that state. Avoid storing credentials, transcripts or sensitive datasets.

## 2. Natural-language routing and examples

The user's intent—not a command keyword—triggers collaboration. No workflow is mandatory for every request.

| Situation | Action |
| --- | --- |
| “Fix this small bug”, “Adjust the button” | Work normally; no ticket or peer notification if no material shared impact. |
| “Let Astra implement this”, “Pass this design to Gemini” | Read task protocol, persist agreed contract, announce task ID and tell user to switch CLI. Do not launch it. |
| “Gemini gave you T003”, “Do the task just assigned to you” | Use the explicitly selected L2 task or ask for its ID; a host identity alone does not select an inbox or task. |
| “Check the changes Astra just made” | Find relevant implemented task (or use explicitly scoped ad hoc review); review protocol. Do not edit code unless asked. |
| “Let's each design independently” | Exploration protocol, common brief; do not read peer proposal or debate until reveal. |
| “I changed the contract with Astra” / “Tell Gemini this new constraint” | Confirm the task scope and approval; update affected facts and notify the resolved recipients. |
| Resume after interruption / model switch | Ask for the context level; inspect only selected task/checkpoint evidence. Continue from evidence, not last assertion. |
| Unrequested peer involvement, routine fix, brainstorming without decision | Do not create a task or mandate an extra review. |

## 3. Independent exploration

Only on user intent. Create `.ai/explore/<id>/` (e.g. `E001`). Establish a common `brief.md`: problem, user intent, hard constraints, relevant repo baseline/revision, success criteria, open questions. The model can distill discussion; user need not manually draft. Preserve the same input for both; no invented consensus. During blind phase, do not read the other's `gemini.md` / `astra.md`, debates, or incoming peer reasoning. Use a fresh session if prior exposure would spoil independence; report contamination rather than call it blind. Read-only repo research may run in parallel. Own proposal: recommendation, rationale, assumptions, alternatives, risks, verification. After user signals reveal, read both and focus on consequential differences; user controls rounds. Prefer evidence or a small prototype to repeated debate. Persist only approved material outcomes in the shared spec/decision log. Exploration directories are disposable.

## 4. Formal task (only for real handoff or user-requested tracking)

### Asynchronous Astra review

Gemini offers two destinations. An **existing Astra session** gets the usual scoped handoff to its public address. A **new Worker** gets a fresh read-only Codex run. Honor an explicit destination or ask the user to choose. If an address is ambiguous or the chosen backend is unavailable, report that condition and keep the selected route.

For a Worker, agree the review question, evidence and Task/Workstream. If the user authorizes a review before a task ID exists, register Gemini and create a review task as writable coordination operations without a level. Make Gemini responsible for delivery, then select L2 with the returned task ID. The Worker needs no Session or ownership assignment. Use the project's `@COORD@` helper with the requesting Gemini session's private handle. A strictly read-only coordination workspace can check status or retrieve an existing result. Submitting a new job requires writable coordination state; the Codex review itself is always read-only.

```json
{"op":"worker-submit","destination":"worker","level":"L2","actor":"<own handle>","task":"T001","key":"eeg-audit-1","brief":"独立检查 EEG-NAS 的搜索空间是否覆盖已确认的约束。引用证据，指出缺失材料。","files":["design/search-space.md","src/search.py"]}
{"op":"worker-status","level":"L2","actor":"<own handle>","task":"T001","job":"<returned W-id>","workspace":"readonly"}
{"op":"worker-result","level":"L2","actor":"<own handle>","task":"T001","job":"<returned W-id>","workspace":"readonly"}
```

Include the same `ws` on all three requests for a workstream. Only the requesting Gemini session in that scope can retrieve the job. The brief and named UTF-8 files are snapshotted on first submission (up to 128 files and 1 MiB of text). Supply only the user's approved materials; for other formats provide an approved text excerpt. There is no automatic import of either chat, task bodies, inboxes or the repository. Preserve the user's evidence and keep peer proposals sealed for an independent review.

Return the destination, scope and job ID immediately, then continue the conversation. Retrying the same submission key and arguments returns the original job. Status shows observed activity and time, without reasoning text. `unconfirmed` means the supervisor stopped reporting; its cause is unknown. A failed or unconfirmed job is never automatically resubmitted. For a completed job, return `original_review` verbatim with its job ID and attribute any commentary separately to Gemini. During blind exploration, retrieve the original only after reveal. The result is rereadable. Completion does not acknowledge a message, accept the Task, or attest that any test was run.

Use the runtime to allocate a unique task ID, or specify an unused ID under `.ai/tasks/`. Never overwrite a task. Before work, inspect `git status --short`, the current commit and relevant spec. Use full commit IDs, record spec Git revision or content hash, not a mutable branch name. Prefer a clean, committed baseline; never clean/stash/commit existing work without authorization. An unborn branch is not a valid commit baseline: establish an authorized first commit, or explicitly use a noncommitted baseline and the limitations below. If uncommitted user changes already exist, preserve them; record their paths and starting state, take a read-only fingerprint if possible. If overlapping changes cannot be distinguished, obtain a scoped decision or use an authorized isolated branch; do not pretend to attribute all diffs to this task.

Use this handoff in either direction (Gemini → Astra or Astra → Gemini), for a task or a workstream. The shared contract contains the problem both sides may read. Keep the issuer's proposed solutions in a separate, optional note.

```markdown
# T001 — <short title>
The runtime manages owner, reviewer, participation, status and revision in the record header.
Base commit: <full SHA or UNBORN>
Base workspace: <clean or snapshot+pre-existing paths/scope>
Spec revision: <commit/content hash or none>

## Goal and confirmed requirements
<user's intended outcome and context of use, in their own words when wording matters; name the user request or approved decision that establishes each material requirement>

## Evidence and open questions
<original example, observation, reproduction steps or source; distinguish what was observed from what remains unknown>

## Hard constraints
<confirmed limits, existing public contracts and authorized scope, with their sources; include a prescribed approach here only when required by the user or an approved decision>

## Done when
<observable outcome, how to verify it, and any judgment reserved for the user>

## Result

## Review
```

For an ordinary handoff, an optional task-scoped HANDOFF message may accompany the contract. Label it “Candidate from <Gemini/Astra>” and give the idea, what led to it, and what still needs checking. The receiver can question the framing, verify the evidence and choose, adapt or discard the idea within the agreed constraints. If the user adopts a candidate as a requirement, record the approval through the normal contract revision process.

For independent exploration, give both sides the same neutral brief. Keep candidates in the author's own proposal until reveal. A blind read still exposes the shared contract, so keep proposed solutions out of its goal, evidence and completion criteria. After reveal, attribute each side's conclusion and evidence and preserve material disagreement when explaining the result to the user.

### Task Ownership

For an authorized handoff or user-requested task tracking, follow any explicit
assignment from the user. If the user leaves a role open, choose it based on
the task context and the agents' capabilities.

- When creating the task, record the designated implementer as Owner.
  An existing assignment may be changed only with user authorization.
- Assign a Reviewer when the user requests review or when an independent
  check would add meaningful value. Otherwise, use `Reviewer: none`.
- Resolve routine role decisions without asking the user. Ask only when an
  unresolved assignment would materially affect execution, scope, authority,
  or the intended outcome.

Issuer, with user authorization, writes the contract. Owner can choose all internal design details not constrained by the contract. If the goal or done criteria need substantive change, record evidence and alternatives in Result, ask for material approval, then issuer (or user-authorized delegate) revises the contract, increments revision, records why and invalidates affected previous review. No unilateral rewriting of criteria by the implementer/reviewer. Preserve older result/review entries or label them superseded; no archive system required. Status is shared, one writer per phase. User may cancel or supersede an obsolete task (mark CANCELLED with reason).

### Implement

Owner reads full contract/current spec and checks baseline drift; re-evaluate meaningful conflicts before writes. Status `READY` or `REWORK` → `IN_PROGRESS`; use ordinary engineering judgment. Continue unaffected work; only `BLOCKED` if meaningful authorized progress is impossible, record reason, what was tried, remaining work and decision/evidence needed. If partially finished but interrupted, keep `IN_PROGRESS` with progress in Result; if genuinely blocked mark `BLOCKED`. When done, record compact technical facts: contract revision, changed paths, key decisions/why if nonobvious, exact test commands and outcomes/exit codes (failed/skipped/not run distinguished), outstanding risks/limitations, and delivered code identity. Set `IMPLEMENTED` only when the owner believes the agreed work is ready for review. Tests unavailable or unknown must be clearly flagged; if they are required and impossible, don't claim verified completion. Don't auto-commit unless the user authorizes it; never auto-push.

### Bind the delivery and review to real state

Prefer a user-authorized task commit and record full result SHA, branch/worktree, and whether any additional relevant changes remain. Review `git diff <BASE> <RESULT>` and the named commit's actual contents; confirm current checkout matches if running tests on it. `git diff BASE..HEAD` alone omits uncommitted work. For an uncommitted delivery, record current HEAD and a working-state fingerprint from `@SNAPSHOT@` (run with Python 3.9+ from the repo); keep the workspace stable through review. The helper hashes tracked staged/unstaged Git patches and untracked nonignored files, without printing file contents. It is read-only; if unavailable, record exact status and inspect the live working tree including untracked paths; without a reproducible identity don't claim a durable acceptance after switching or edits. Inspect `git diff <BASE>` where BASE exists, `git diff --cached`, `git diff`, `git status --short`, and `git ls-files --others --exclude-standard`; inspect relevant untracked files explicitly. For pre-existing dirty state use the recorded starting scope/evidence; be candid about attribution limits. Include relevant ignored runtime inputs, external dependencies, datasets, and submodules separately if they affect the test; the fingerprint does not establish their content or runtime reproducibility.

### Review / rework

Reviewer first reads the authorized contract, relevant spec and actual diff/runtime; avoid reading Result until forming an independent preliminary judgment (read sections selectively, e.g. print only before `## Result`). A shared task file is behavioral separation, not enforced blindness; if exposed, disclose it, don't fake independence. Verify delivered identity without relying on claims (read only the necessary identity fields from Result if needed); inspect and run relevant checks; verify code state again if tests or other work could have modified it. Review relevant technical correctness, unmet criteria, risks, regression and user intent/UX (use real screenshots/interactions when relevant). No stylistic nitpicking; distinguish blocking defects from suggestions. Subjective uncertainty belongs with user, not invented approval. Only then consult full Result for context. Record Review with reviewed contract revision, exact result commit or workspace fingerprint, evidence, findings and conclusion. Use `REWORK` for an observed unmet criterion. If a required check cannot run during review, leave the task at `IMPLEMENTED` and report the missing evidence in the task scope. Resume review after the evidence becomes available. The Owner may set `BLOCKED` during `IN_PROGRESS`. Owner handles rework, appends a new Result, and reviewer repeats affected checks. If contract or relevant code changes after acceptance, old acceptance is historical, not approval of the new state. No automatic edits by reviewers unless user separately delegates implementation; preserve review independence.

### Reporting acceptance

In Result, the Owner records their conclusion and evidence. In Review, the Reviewer records their own judgment against the contract. When relaying either to the user, keep material reservations and differences attributed to their author. A short explanation can link to the original scoped Result or Review.

| Evidence for this delivery | What to report |
| --- | --- |
| The assigned Reviewer verified the agreed criteria and recorded `progress` as `ACCEPTED`. | “Reviewer C-G001 passed the export checks for contract r2 on the reviewed build.” Identify the actual delivery, checks and any unresolved experience question. |
| The user explicitly accepted this delivery. | “The user confirmed the export experience on the reviewed build.” Identify the delivery and confirmed scope, and cite the user's statement or its source. If Reviewer is User or none, the Owner records it with `user-accept` from `IMPLEMENTED`. |
| Only the Owner has delivered, or an older record shows only `ACCEPTED`. | Report the delivery or historical status and the available evidence. If the source of acceptance is unknown, say so. |

If the user later confirms a delivery already passed by a Reviewer, report both judgments separately with their sources. The existing Reviewer entry stands. A user authorizing a review or approving a plan establishes only that authorization.

## 5. Context and scoped communications (v0.2.0)

### Start and select scope

Read the resident rule first. Choose L1/L2/L3 before discovering existing tasks, sessions, inboxes or checkpoints. For an explicitly requested first handoff without a task ID, the receiver may register its own address and the issuer may register and create the task as dedicated writable coordination requests. Omit level on those administrative operations. Return public IDs only, then select L2 with the allocated task ID before reading task content. Keep strict read-only until the user authorizes switching to a writable workspace. Work only in the scope selected for this chat. Neither the last open session nor an agent name identifies a conversation. L1 requires no registry and no messages, including project notifications and unread counts. Ordinary code investigation in L1 can read relevant project sources, materials and the current approved project facts. Proposed decisions do not belong in SPEC or DECISIONS.

L2 reads one specified task and a relevant workstream. L3 reads one specified predecessor's checkpoint slice and matching work; show only scope IDs if several need selection. Do not read another stream's body to decide which one to use. A message addressed to the correct Session can still be about the wrong task. Unscoped PROJECT/SESSION notifications remain untouched until the user explicitly broadens scope. Strict read-only also forbids acknowledgement, registration, takeover, saving checkpoints or clearing a message. A fresh chat is required for strict reasoning independence after exposure. For blind review/exploration avoid peer results and inboxes until reveal; use the blind read option.

### Runtime interface

Run `python -B @COORD@ --root <code checkout>` with one UTF-8 JSON object on standard input. The helper returns JSON; errors yield a nonzero exit. JSON examples below use placeholder handles and IDs. The helper defaults to shared workspace. Pass `"workspace":"readonly"` for read-only work, or `"workspace":"isolated"` for an explicitly attached isolated worktree. Pass the chosen level on scoped requests. Never store a session handle in project records, shared chat summaries, messages or Git. Keep it only in the owning conversation or a private per-chat credential facility. Reusing an ID alone cannot authenticate as its writer. Local files are cooperative safeguards for clients sharing an OS account.

```json
{"op":"context","level":"L1","workspace":"readonly"}
{"op":"register","agent":"ASTRA","registration_key":"<fresh private random key for this chat>"}
{"op":"context","level":"L2","task":"T001","ws":"WS-B","actor":"<own handle>"}
{"op":"checkpoint","actor":"<own handle>","task":"T001","ws":"WS-B","body":"Tested approach, observed failure, code revision and next step."}
{"op":"context","level":"L3","from":"C-A001","workspace":"readonly"}
{"op":"register","agent":"ASTRA","resumes_from":"C-A001"}
{"op":"context","level":"L3","from":"C-A001","task":"T001","ws":"WS-B","actor":"<new handle>"}
```

A context read alone does not register. Generate a private registration key once with Python secrets.token_urlsafe(32); retry registration with the same key if the response is lost. Each distinct chat generates a different key. On a writable L3 continuation select the checkpoint then register a fresh successor before acting. A strictly read-only preview may remain unregistered. Use slice=PROJECT to explicitly select a project-only checkpoint when there are several choices. A task-only checkpoint never implicitly selects a workstream. Save scoped evidence, failed attempts and next actions. Close explicitly with close and approved=true. Pending deliveries require handoff or explicit retain_pending=true. Open registrations may be offline. Closing a terminal does not close the registration.

### Ownership and workstreams

The task header is authoritative for direct participants, integration Owner and task Reviewer, including a task with no streams. Each stream header is authoritative for its participants, Owner and Reviewer. Session metadata is authoritative for host and open/closed status. IDs in checkpoint names are recovery pointers, not routing memberships. No global hand-maintained index. Use create-task/create-stream for new work. Keep legacy tasks intact until the user confirms their adoption with adopt-task, original SHA256, roles and original status.

```json
{"op":"create-task","actor":"<own handle>","owner":"C-A001","reviewer":"C-G001","body":"User-confirmed goal and sources, original evidence, open questions, confirmed constraints, completion criteria, baseline and spec revision"}
{"op":"create-stream","actor":"<integration owner handle>","task":"T001","ws":"WS-B","owner":"C-A002","participants":["C-G001"],"body":"Boundary, shared interfaces, deliverable and completion criteria"}
{"op":"progress","actor":"<owner handle>","task":"T001","ws":"WS-B","revision":1,"status":"IN_PROGRESS","body":"Baseline and current work"}
{"op":"takeover","actor":"<successor handle>","from":"C-A001","task":"T001","ws":"WS-B","revision":2,"approved":true,"key":"approved-transfer-1"}
```

Workstream is optional. Scope IDs are local to their task. Use revision checks for updates; reread after a conflict. Takeover requires explicit approval and a successor link, transfers only that scope and its pending deliveries, and invalidates the prior writer's ownership. Task-wide takeover and individual stream ownership are separate. Formal acceptance refers to the actual tested revision. Report who accepted it as described under Reporting acceptance.

### Delivery

When changing an approved contract, use revise with the expected revision, new contract body, user approval and reason. The former record stays under the task's history directory, the contract revision increases, and prior acceptance is invalidated. Use progress with IN_PROGRESS for a scoped interim update. Use blind=true on a context read for independent review; the helper excludes peer results, reviews and message bodies.

The target determines recipients. The task and optional ws determine which context may open the body. For SESSION or PROJECT use an unscoped message only if the content is truly unscoped. A task broadcast gets the union of direct and workstream participants; a workstream route includes its participants. Explicit AGENT routes default to one matching session in the supplied task/stream, or project if none is supplied. Zero matches reports no recipient; multiple matches require exact selection or explicit all=true. PROJECT snapshots all registered open sessions, including the sender if eligible. Persist user-approved project facts before notification. Never promote proposals because they arrived with a broadcast.

```json
{"op":"send","actor":"<sender handle>","key":"interface-change-1","target":"TASK","task":"T001","type":"UPDATE","body":"Why: approved schema change. Message: see current spec. Action: recheck your interface."}
{"op":"send","actor":"<sender handle>","key":"handoff-2","target":"SESSION:C-A002","task":"T001","ws":"WS-B","type":"HANDOFF","body":"See the confirmed T001 / WS-B contract. Candidate from Gemini: key requests by export ID. Repeated clicks were observed; check whether duplicate requests actually reach the service."}
{"op":"send","actor":"<sender handle>","key":"stream-3","target":"WORKSTREAM","task":"T001","ws":"WS-B","body":"Review the revised contract."}
{"op":"send","actor":"<sender handle>","key":"project-4","target":"PROJECT","body":"Confirmed project standard is recorded in DECISIONS."}
{"op":"send","actor":"<sender handle>","key":"astra-5","target":"AGENT:ASTRA","task":"T001","all":true,"body":"Explicit user-requested fan-out."}
{"op":"notifications","actor":"<own handle>","level":"L2","explicit_notifications":true}
{"op":"ack","actor":"<own handle>","level":"L2","task":"T001","ws":"WS-B","delivery":"<delivery ID>","outcome":"Recorded approved impact in T001 revision 3."}
```

Use a stable send key per logical action; on timeout retry the same key and payload. Send metadata freezes recipient IDs and per-recipient delivery IDs. Independent copies live under each recipient's inbox, partitioned by task/stream or unscoped bucket. Ordinary L2 never opens the unscoped bucket. Acknowledging an unscoped notification also requires explicit_notifications=true and explicit scope expansion. Read first, persist relevant effects with an idempotency key or durable evidence, then acknowledge. Each receiver clears only their own body. Receipt tombstones and send snapshots support retries. A delivered file never proves a person or CLI has read it. External shell actions cannot be made exactly-once by a file receipt. The helper serializes state operations and recovers interrupted batches. Read-only operations refuse pending recovery. With user authorization in a writable context run {"op":"recover"} to finish it.

### Legacy and workspaces

For published project decisions use publish-fact with file, full new body, approved=true, approval source, and expected_sha256 of the previous bytes (null for an absent file). A L1 user-approved fact edit requires no registration or message reads. If another writer changed the document, reread before merging. Before consuming unscoped notices from a predecessor, the authorized successor may use transfer-preview (from, approved=true, explicit_notifications=true) to examine routing headers only, then transfer-notifications with an explicit deliveries list. To check receipt metadata without opening bodies, the sender uses delivery-status with its own key.

Starting IN_PROGRESS reserves that code checkout for the assigned Owner; multiple sessions need different approved checkouts for simultaneous code changes. Each operation has its own scope: a user changing the chat's workspace to strictly read-only must pass workspace=readonly to subsequent commands. Replay protects interrupted local process writes; network filesystems, power loss and external side effects require separate recovery guarantees.

Project upgrade previews first, preserves originals and backups, and never sends old messages. An authorized administration context may run legacy-inventory (actor, explicit=true, side=astra|gemini) to freeze the source and get its hash, tentative boundaries, classifications and pending line intervals. Use legacy-preview with expected_sha256, first and last to open only a selected interval. legacy-classify records a confirmed task/stream while leaving the entry pending. legacy-deliver requires approved=true and a confirmed recipient or list of exact recipients. A task broadcast additionally requires approved_task_broadcast=true. Unscoped deliveries require explicit_notifications=true. Source drift and overlapping resolved ranges stop migration; never automatically broadcast based on the old filename.

## 6. Workspace isolation and recovery

A primary initialized checkout owns the canonical .ai state and approved project facts. An explicitly approved, already existing linked worktree can be attached by running the primary runtime with --root pointing to that checkout and {"op":"attach","approved":true}. The helper verifies Git common-directory identity. No helper creates, deletes, merges or copies worktrees. For local-only rules in a linked worktree, explicitly load the primary resident entry at startup; verify host discovery separately. A private checkout may have committed resident rules; use the attached runtime's canonical facts and note the revision of branch-local code. Pick shared, strictly read-only, or isolated workspace independently of L1/L2/L3. One primary code writer per worktree; other participants may investigate read-only. For independent code changes request user approval for an isolated worktree based on an agreed commit. Ignored datasets, weights, local environments and private settings require explicitly approved external paths or read-only mounts. No credential or dataset copy is implied. Coordinate shared interfaces, branch and tested commit before integration.
