# Newtonite Operations Tracker

A team-scoped work tracking API built for the Newtonite Software Engineering Challenge. It supports JWT login, team membership and roles, searchable work item lists, an approval workflow, and an activity history.

## Current status

The backend and PostgreSQL schema are implemented. The browser UI and hosted deployment setup are not implemented yet. The API's interactive documentation is available at `/docs` while the service is running.

## Technology

- Python 3.12 and FastAPI
- PostgreSQL 16
- SQLAlchemy 2 and Alembic
- Pydantic Settings
- JWT access tokens (PyJWT); Argon2 password hashes (pwdlib)
- Docker Compose for local development
- pytest for critical workflow behavior tests

## Run locally with Docker

Prerequisites: Docker Desktop with Compose enabled.

In PowerShell, from the repository root:

```powershell
Copy-Item .env.example .env
docker compose up --build -d
docker compose exec api alembic upgrade head
docker compose exec api python -m app.seed
```

Open [http://localhost:8001/docs](http://localhost:8001/docs). The API listens on port `8000` inside the container and is published at `8001` on the host. PostgreSQL is published at host port `5432` and stores data in the `postgres_data` Docker volume.

The seed command creates three teams, demo users, and 1,200 sample work items by default. It can be rerun safely. For a different item count, use `docker compose exec api python -m app.seed --items 100`.

### Demo login

The seed script prints the demo password and account emails. It is currently `NewtoniteDemo2026!`; use an account from the Operations, Engineering, or Payments team, for example `member.ops@newtonite.local`. These shared credentials are for local demonstration only. Do not use them in a public deployment.

In Swagger UI, run `POST /auth/login` with the email and password, then click **Authorize** and enter the returned access token. The token lifetime is 60 minutes.

## Main API routes

All work item routes require `Authorization: Bearer <access-token>`.

| Route | Purpose |
| --- | --- |
| `POST /auth/login` | Exchange demo credentials for an access token |
| `GET /auth/me` | Return the authenticated user |
| `GET /teams` | List the current user's teams and roles |
| `POST /teams/{team_id}/items` | Create a work item for a team |
| `GET /items` | List accessible items; supports team, status, priority, assignee, text query, cursor, and limit filters |
| `GET /items/{item_id}` | Read an item with up to 50 latest activity events |
| `POST /items/{item_id}/claim` | Atomically claim an unassigned item |
| `PATCH /items/{item_id}` | Update item fields using an expected version |
| `POST /items/{item_id}/transition` | Move an item through an allowed workflow transition |
| `GET /health` | Check that the API process is running |
| `GET /health/ready` | Check that the API can query PostgreSQL |

Workflow: `open` → `in_progress` → `awaiting_approval` → `resolved` → `closed`. Only a team Lead can approve an item from `awaiting_approval` to `resolved`. Viewers can read team data; members, leads, and admins can create or change work items. A user without membership receives `404` for team-scoped resources.

## Database migrations

Apply schema changes with `docker compose exec api alembic upgrade head`. The initial migration is in `alembic/versions/`. Do not use `Base.metadata.create_all()` as a substitute for applying migrations to a deployment database.

## Tests

The tests use a separate PostgreSQL database named `newtonite_test`. The fixture refuses to run against another database name, creates that database if needed, and recreates its schema for the test session. It does not point at or clear the local development database.

```powershell
docker compose up --build -d
docker compose exec api pytest -q
```

The current suite covers simultaneous claims, stale version updates, Lead approval permissions, cross-team access, and invalid workflow transitions.

## Configuration and deployment notes

Environment variables are read from `.env` locally. `.env.example` shows the local defaults. For a hosted deployment, set `DATABASE_URL` to the provider's PostgreSQL connection string in SQLAlchemy's `postgresql+psycopg://` form and set `JWT_SECRET` to a long, randomly generated secret. The Dockerfile's final stage is `production`; Compose selects the `development` stage for local reload and test support.

The application does not yet include a frontend or a Render deployment configuration. Before publishing, replace demo credentials, use provider-managed secrets and database, apply Alembic migrations, and verify the production health endpoints.

## Repository layout

```text
app/                 FastAPI app, routers, models, settings, and seed script
alembic/             Database migration configuration and revisions
tests/               Critical behavior tests
compose.yaml         Local PostgreSQL and API services
Dockerfile           Development and production container targets
ENGINEERING_DECISIONS.md  Design choices and tradeoffs
```
