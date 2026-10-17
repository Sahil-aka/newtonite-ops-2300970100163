# Engineering Decisions

This document explains the important choices behind the Newtonite Operations Tracker: the problem each choice addresses, alternatives considered, what this implementation does, and the costs of that choice.

The Newtonite Candidate Brief is the source of required challenge behavior. The separate GU CCIO student execution plan is advisory. The implementation prioritizes a coherent work-item workflow and correctness under concurrency over implementing every optional suggestion in that plan.

## 1. Relational data model and append-only activity events

**Context.** Work belongs to a team, users can belong to multiple teams with different roles, and item changes need to remain explainable. A manager should be able to see who changed the owner or state and when.

**Options considered.** Store everything in one denormalized JSON document; use relational tables with a separate event log; or introduce event sourcing as the primary write model.

**Choice.** Use PostgreSQL tables for `users`, `teams`, `memberships`, `work_items`, and `activity_events`. A membership is the relation between one user and one team and stores the role for that team. A work item stores its current state for efficient queues; activity rows store the actor, event type, timestamp, and old/new values. Comments are represented as append-only activity events instead of a separate comments table. Alembic manages schema changes.

**Why this fits.** Relational constraints and joins express team membership and assignment rules directly. Keeping a current work-item row makes queue queries simple, while the separate activity table provides a readable audit timeline without making the whole application event-sourced.

**Trade-off.** Every important mutation must write its activity event in the same transaction as the item change. Activity data grows continuously, and detail currently returns only the latest 50 events; a larger deployment would need history pagination and a retention strategy.

## 2. JWT authentication and per-team authorization

**Context.** Employees may hold different roles in different teams. Hiding an action in the browser cannot protect the API from direct or modified requests.

**Options considered.** Use shared demo credentials only; use server-side sessions; or use signed access tokens and check team roles from the database on protected operations.

**Choice.** Passwords are stored as Argon2 hashes via `pwdlib`. Login returns a signed JWT access token with a 60-minute expiry. A FastAPI dependency validates its signature and expiry, loads the active user, and team-scoped routes check the user's membership and role. An inaccessible team is reported as `404` to avoid revealing whether another team's resource exists. A Lead alone may approve the transition from `awaiting_approval` to `resolved`.

Signup is provided as a demonstration convenience, although the challenge does not require it. A new signup is normalized, password-hashed, and automatically added to the Operations team as a Member. There is no self-service role choice, because allowing a registrant to choose Lead or Admin would defeat the permission model.

**Trade-off.** Database-backed membership checks keep role changes effective without embedding role claims in long-lived tokens, but protected requests perform database work. Tokens have no refresh or revocation mechanism, and public signup currently has no invitation or throttling. The shared seeded demo password is deliberately unsuitable for sensitive or production data.

### Role and action matrix

| Action | Viewer | Member | Lead | Admin |
| --- | --- | --- | --- | --- |
| Read own team's work and activity | Yes | Yes | Yes | Yes |
| Create, edit, claim, assign, comment | No | Yes | Yes | Yes |
| Perform ordinary allowed transitions | No | Yes | Yes | Yes |
| Approve `awaiting_approval` to `resolved` | No | No | Yes | No |
| Manage teams or memberships | No | No | No | Not implemented |

The Admin role currently has Member-level work-item permissions. This is an explicit scope limitation, not a claim that team administration is implemented.

## 3. Explicit concurrency control and transactional history

**Context.** Two people can claim the same item, and a user can submit edits based on a stale view. A successful response should not silently overwrite someone else's work. The activity timeline must agree with the saved state.

**Options considered.** Assume conflicts are rare; lock rows for every interaction; or use atomic conditional updates for claims and optimistic versions for edits.

**Choice.** Claim uses a database update that only matches while `assignee_id` is empty. One concurrent request can update the row; a competing request gets a conflict. Work-item updates carry `expected_version`; the database update succeeds only if the stored version matches, then increments it. Assignment and workflow transitions use the same stale-version protection. The item change and its corresponding activity event are committed in one transaction.

**Why this fits.** The database decides the winner, so correctness does not depend on which request reaches one application process first. Optimistic checks avoid holding a row lock while a person edits in the browser. `409 Conflict` gives the UI a clear signal to refresh and explain the conflict.

**Trade-off.** The user may need to reopen an item after a conflict. This design protects claim and stale-write behavior, but it does not implement general idempotency keys: retrying a create request at the API level can still create another item. The interface disables its submit button while a request is pending, which only reduces accidental browser double-submits.

## 4. Server-side filtering and cursor pagination

**Context.** The challenge anticipates tens of thousands of active items and a growing history. Sending all rows to a browser and filtering there becomes slow and increases data exposure.

**Options considered.** Fetch all team records and filter in JavaScript; use offset pagination; or filter in PostgreSQL and use a cursor with stable sort keys.

**Choice.** The `/items` endpoint applies team, status, priority, assignee, and text filters in PostgreSQL. Search uses `ILIKE`. Cursor pagination orders on `updated_at` and the unique `id` tie-breaker, and the browser requests more data using the returned cursor. Composite indexes support common team/status, team/assignee, and team/priority access patterns.

**Why this fits.** Only the current page is transferred and rendered. A unique tie-breaker avoids ambiguous ordering when multiple work items have the same timestamp.

**Trade-off.** `ILIKE` is easy to understand and adequate for this sample, but a contains search can become expensive on large datasets. No trigram or full-text index has been added without evidence that it is needed. Dashboard summary cards describe the loaded page rather than issuing separate whole-result counts.

## 5. Keep the first slice synchronous and deployable as one service

**Context.** The challenge allows notifications, enrichment, or other secondary operations to run asynchronously, but it does not require any of those features. The assessed one-day timebox favors a small number of complete, explainable paths.

**Options considered.** Add a Redis-backed queue or transactional outbox and worker immediately; or keep current user-visible work synchronous and add asynchronous processing only with a real secondary task.

**Choice.** Work-item mutations, authorization checks, and activity writes complete in one FastAPI request and one database transaction. A separate worker, queue, retries, and notification delivery are not included. The static HTML/CSS/JavaScript interface is served by the same FastAPI service. Docker Compose starts that app with PostgreSQL for local development; the production Docker target applies Alembic migrations, seeds demo data, and starts Uvicorn. Render hosts the container and Supabase hosts PostgreSQL for the public demo.

**Why this fits.** There is no background side effect to fail or retry, so introducing a queue would add operational complexity without user value. The same-origin app avoids a separate frontend build and CORS configuration, and Compose gives a reviewer a short, repeatable setup.

**Trade-off.** There is no background processing or notification delivery. Production seed data uses intentionally public demo credentials and must not be used for real company work. Render's free service may spin down after inactivity; an external cron-job.org request to `/health` every 10 minutes reduces cold starts but cannot guarantee continuous availability. Secrets such as `DATABASE_URL` and `JWT_SECRET` are supplied through Render environment settings and must not be committed.

## Test strategy

Tests focus on expensive-to-debug correctness failures rather than page rendering: simultaneous claims, stale edits, Lead approval, invalid workflow jumps, cross-team reads, assignment scope, and consistency of activity records. The test fixture requires a disposable PostgreSQL database explicitly named `newtonite_test` and checks that name before it creates or drops tables. The current repository has no automated browser end-to-end tests.

## Intentional omissions and revisit triggers

- **Idempotency keys:** Add if clients need safe retries for create operations or if duplicate creation becomes a real operational risk.
- **Transactional outbox and worker:** Add when a durable asynchronous side effect, such as notifying an assignee, is introduced. Write the outbox row in the same transaction as the item change; make handlers idempotent and retry with a limit.
- **Activity pagination:** Add before item timelines can exceed a practical response size; retain a stable event cursor.
- **Search indexing:** Measure query plans and latency first; add PostgreSQL trigram/full-text indexing when `ILIKE` is too slow.
- **Invitation and membership management:** Add before signup is exposed beyond a seeded demonstration environment.
- **Token revocation and rate limiting:** Add before the application handles real users or sensitive data.

## If the system grew significantly

Keep the API stateless so it can run multiple instances; use managed connection pooling and monitor database pool usage. Measure slow queries before adding indexes or a dedicated search service. Partition or archive activity data only when growth justifies the extra operational work. Introduce a durable queue with an outbox when asynchronous work exists. Revisit team membership administration and token lifecycle as product needs become clearer.
