
You are building Vayumi Server 1 — the TypeScript identity, session, integration, and push backend.

BEFORE writing any code, you MUST read these files in full and understand them:

1. PLAN.md — the frozen architecture. Every decision is here. Do not invent alternatives. **Read the Server 2 Contract section** before touching email pipeline or internal JWT code.
2. doc/roadmap.md — the full 12-step overview so you know what comes before and after.
3. doc/history.md — what has been done so far. Do not redo completed work.
4. doc/tracker.md — build progress + architecture flow diagrams. Update this after each step.

Then determine which step to work on:
- Look at PLAN.md Section 8 (Phase plan). Find the first step with status ⬜. That is the current step.
- Read its step file: doc/step-<N>.md (where N is the step number you found).
- If a previous step exists (doc/step-<N-1>.md), read that too so you know what code already exists.
- If the step file does not exist yet, STOP and tell me. I need to create or approve the step file before you build anything.

RULES YOU MUST FOLLOW:

1. ONLY build what the step file says. If you feel tempted to add something from a later step, stop. Write it as a note for that later step instead.

2. No temporary hacks. Every line of code must be the real implementation shape even if it's a subset of the final behavior. No TODO comments that say "implement later." No placeholder functions that return hardcoded values except where the plan explicitly allows stubs (e.g. webhook stubs in Step 10).

3. Match the folder structure in PLAN.md exactly. Same file names, same directory layout. Do not reorganize.

4. Match the function and module names in PLAN.md exactly. When the plan says `processIncomingEmail()`, name it that. When it says `IEmailProvider`, use that interface.

5. Use the exact dependencies from PLAN.md Packages section. Do not add new dependencies without stating why. Do not upgrade to alternatives.

6. If this step touches API routes, keep existing routes working. If it does not touch a module, that module must still work unchanged.

7. Write tests as specified in the step file. Every step must end with green `npm run typecheck` and `npm run build`. Add unit/integration tests when the step file asks for them — test real pipeline behavior, not mocked trivia.

8. After completing the step, run the acceptance test from the step file. List each acceptance test item and confirm pass/fail.

9. Do not modify PLAN.md, doc/roadmap.md, doc/history.md, or doc/tracker.md during implementation. Update those only in the completion phase (see below).

10. Do not commit to git unless I ask you to.

11. Keep code clean: no commented-out code, no debug prints left behind, no unused imports. Use TypeScript strict types. Follow the Pino logging pattern from the codebase.

12. If something in the step file is ambiguous or seems wrong, ASK ME before implementing. Do not guess.

13. Don't fake anything — wire real OAuth flows, real DB writes, real provider calls. Test with realistic cases.

14. If you remove anything wrong, remove permanently — do not leave legacy shims or dead code paths.

15. Server 1 never writes Server 2's tables. Server 2 never writes Server 1's user/session/OAuth tables. Shared Postgres/Redis infra is fine; table ownership is not shared.

16. OAuth tokens at rest are AES-256 encrypted via `tokenVault.ts`. PII masking for AI classify stays in-memory only — never persist `maskingMap`.

17. Service JWT for Server 2: `signInternalServiceJwt()` using existing `JWT_PRIVATE_KEY`, payload `{ scope: 'internal', iss: 'server1' }`. No separate service token env var.


ENVIRONMENT:
- Node.js + TypeScript (ES modules). Run from `Server1/`.
- `npm run dev` — tsx watch. `npm run build` + `npm start` for production shape.
- Postgres + Redis from `.env` (`DATABASE_URL`, `REDIS_URL`). Often shared cloud URLs with Server 2.
- `DATABASE_AUTO_MIGRATE=true` runs Drizzle migrations on boot.
- JWT: RS256 with `JWT_PRIVATE_KEY` / `JWT_PUBLIC_KEY` PEM pair.
- Boot: `npm run dev` (default port from `PORT`, typically 3001).
- Verify: `npm run typecheck` && `npm run build`.


AFTER all acceptance tests pass, do the COMPLETION PHASE — update all tracking files:

1. PLAN.md Section 8: change the status of the completed step from ⬜ to ✅.
2. doc/history.md: add a new entry with today's date, scope, what was built, files created/changed, and which plan sections it relates to. Follow the existing entry template.
3. doc/roadmap.md: update the status emoji of the completed step from ⬜ to ✅.
4. doc/tracker.md: update the build progress grid (change completed step to ✅, update counts). Add/update architecture flow diagrams if this step changes how data moves.
5. If the next step does not have a step file yet (doc/step-<N+1>.md), create it as a stub following the skeleton in PLAN.md Section 9. Set its status to ⬜ pending.
6. Tell me all acceptance tests passed and the tracking files are updated. Then wait for me to say "commit" before making a git commit.


START by reading the files listed above, then tell me which step you are going to implement and present your implementation plan (which files you will create/modify, in what order) before writing any code. Wait for my approval.
