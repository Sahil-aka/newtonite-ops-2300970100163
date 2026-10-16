# Engineering Decisions

This document records the main implementation choices for the Newtonite Operations Tracker and the tradeoffs that fit a short assessment build.

## Backend and API

**FastAPI** provides typed request validation, dependency injection, and generated OpenAPI documentation. The API is split into auth, team, and work item routers. Keeping the first version as one service is quick to develop and explain; the boundaries can later be split if scale or team ownership calls for it.

## Data storage

**PostgreSQL 16** is used in development and is intended for deployment. **SQLAlchemy 2** provides typed ORM models and explicit queries; **Alembic** tracks schema evolution. Docker Compose persists local data in a named volume, so stopping containers does not normally delete the database. Test setup uses a separately named `newtonite_test` database and validates that name before modifying its schema.

## Authentication and authorization

Passwords are verified with **Argon2** hashes via pwdlib. Login returns a signed **JWT access token** with a 60-minute expiry; FastAPI's HTTP Bearer support extracts the token, and PyJWT validates its signature and claims. Team membership is checked against the database on protected requests. Team roles are `viewer`, `member`, `lead`, and `admin`; only a Lead can approve an item awaiting approval.

This keeps authentication explainable and avoids server-side session storage. The current version has no refresh tokens, logout/revocation list, account registration, or login throttling. Use a high-entropy secret from the deployment environment and do not use seeded demo credentials publicly.

## Work item access and listing

Work item reads are scoped through the user's team memberships. Unknown or inaccessible teams and items return `404` to avoid exposing whether another team's records exist. List filters run in PostgreSQL. Cursor pagination sorts by `updated_at` and `id`; the composite key gives stable ordering when timestamps match and avoids loading the entire result set.

## Concurrency and workflow integrity

Claiming uses a conditional database update that succeeds only while `assignee_id` is empty. Concurrent requests therefore cannot both claim the same item; the losing request receives `409 Conflict`.

Edits include an `expected_version`. Updates increment the version only when it matches the current row, rejecting stale edits with `409 Conflict`. Workflow changes check the allowed transition, expected version, and role. Each successful mutation records its activity event in the same transaction as the item change, so the event history cannot claim a change that failed to save.

## Activity history

The `activity_events` table stores the actor, event type, and old/new values for item creation, claims, edits, and transitions. Item detail returns the latest 50 events to keep responses bounded. A fuller audit policy could add retention rules, stronger immutability guarantees, and pagination for long histories.

## Seed data

`python -m app.seed` creates deterministic team/user identities and sample items, and can be rerun without duplicating those rows. A shared password keeps local demonstrations easy; because it is intentionally shared, it is only suitable for local assessment use.

## Container strategy

The Dockerfile has a `development` target with reload and pytest support and a leaner final `production` target. Compose uses development; a hosted container build uses the final stage by default. This keeps the local feedback loop convenient while giving deployment a non-reloading server command.

## Deliberate scope limits

- The frontend is not implemented yet; Swagger UI is currently the interactive API surface.
- The demo has no registration, password reset, invitation, or team management endpoints.
- There is no external monitoring, rate limiting, or background job system.
- Render deployment wiring and public production configuration remain to be completed.
- The critical workflow tests exercise router behavior against PostgreSQL; broader API integration and browser tests can be added with the frontend.
