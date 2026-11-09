# Locus

<p align="center">
  <img src=".github/assets/locus_mockup.png" alt="Locus Mockup">
</p>

<p align="center">
  <b>🇺🇸 English</b> · <a href="README.md">🇷🇺 Русский</a>
</p>

**Locus** is a fast self-hosted online school diary with a shared lesson schedule, bell times and a flexible homework tracker with per-student completion statuses.

It combines a school-wide schedule and a single homework pool with individual progress tracking for every student. Built on FastAPI and async SQLAlchemy 2.0, rendered server-side with Jinja2 and HTMX, styled in pure AMOLED black, with PWA and Web Push support.

> [!IMPORTANT]
> **The interface is Russian only.** The code and these docs are in English, but the UI strings and date formats are hardcoded in Russian — there is no i18n layer yet. Documentation under `docs/` is also Russian for now.
>
> If you would actually use Locus in English (or any other language), open an issue with a prefilled title: [i18n: English UI](https://github.com/1hebread/Locus/issues/new?title=i18n%3A+English+UI&labels=enhancement). Enough requests and localization gets built.

## Features

- 📅 **Shared schedule and bell times**: lessons by weekday, start and end times, recesses, classrooms and teacher names. The schedule and the subject list are shared by all users and managed by an administrator.
- 📚 **Shared homework pool**: any authenticated user can add, edit or delete an assignment.
- ✅ **Personal completion tracking**: each student has their own `TODO` / `DONE` status, stored in the isolated `homework_completions` table.
- 👥 **Subgroup support**: split classes into subgroups (foreign languages, for example) across the schedule, homework and push notifications.
- 🧹 **Duty roster**: who is on duty for each weekday, with optional binding to a user by login (`Ivan I. (ivan)`) and a highlight of your own line for today.
- 🔔 **Web Push notifications**: background browser and PWA pushes (VAPID) on homework creation, update and deletion, filtered by subgroup and sent to every active user except the author of the change.
- 📜 **Change history (audit log)**: a transparent trail of homework edits with the author, timestamp and changed fields (`homework_events`). The last editor is shown in the lesson modal, and the full feed is at `/admin/history`.
- 💡 **Smart defaults**: when adding homework, the next date and the matching lesson are preselected.
- 🧹 **Automatic cleanup**: old assignments are rotated out after a configurable retention period (`HOMEWORK_RETENTION_DAYS`).
- 📱 **PWA and AMOLED design**: a responsive ultra-dark interface, installable to the home screen, with a floating navigation dock and iOS standalone tweaks.
- ⚡ **Reactive UI without an SPA**: instant feedback and partial DOM updates through HTMX, no heavy client-side framework.
- 🔑 **Public REST API**: a full `/api/v1` with a daily summary (`/summary`), personal API keys (`lk_...`) and JWT, ready for bots and third-party integrations.
- 🛡️ **Security and administration**: an admin panel (`/admin`), user management, password changes, API key issuing, and no public registration.

### Tech stack

| Component / Layer | Stack | Notes |
|---|---|---|
| `Web app and API` | FastAPI, Pydantic v2, Uvicorn | One async server serving both SSR routes and the `/api/v1` REST API, authenticated with session JWTs and long-lived API keys (`lk_...`). |
| `Database and ORM` | PostgreSQL / SQLite, SQLAlchemy 2.0, Alembic | Strictly async access (`AsyncSession`). PostgreSQL (`asyncpg`) in production, SQLite (`aiosqlite`) for local tests. |
| `Frontend` | Jinja2, HTMX, Tailwind CSS, vanilla JS | Server-side rendering with partial DOM swaps via HTMX, pure AMOLED palette (`#000000`), separate optimized layouts for desktop and mobile. |
| `Notifications and PWA` | Web Push (VAPID), Service Worker, pywebpush | Push delivery to browsers and PWAs on homework changes, plus a PWA manifest and standalone mode. |

## Quick start

### Requirements

- Python 3.12+
- Docker and Docker Compose (to run PostgreSQL)
- [`uv`](https://github.com/astral-sh/uv) package manager

### 1. Configure the environment

Copy the environment template:

```bash
cp .env.example .env
```

Fill in `.env`:

- `DATABASE_URL` — PostgreSQL connection string (`postgresql+asyncpg://admin:secret@localhost:5432/diary`).
- `SECRET_KEY` — application secret used to sign session JWTs (at least 32 characters in production).
- `ENCRYPTION_KEY` — optional key for encrypting sensitive fields (derived from `SECRET_KEY` when left empty).
- `ADMIN_USERNAME` — login of the initial administrator (used when initializing an empty database).
- `ADMIN_PASSWORD` — password of the initial administrator (at least 8 characters).
- `PORT` — web server port (default `8010`).
- `TIMEZONE` — diary timezone (default `Asia/Almaty`).
- `HOMEWORK_RETENTION_DAYS` — how long old assignments are kept, in days (default `30`).
- `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT` — keys for Web Push notifications.

> [!NOTE]
> Generate a VAPID key pair with the bundled utility:
> ```bash
> uv run locus-vapid
> ```

> [!NOTE]
> A complete template with every environment variable is in `.env.example`.

### 2. Start the database with Docker Compose

Run PostgreSQL in the background:

```bash
docker compose up -d
```

Follow the logs:

```bash
docker compose logs -f
```

Stop the database:

```bash
docker compose down
```

### 3. Run the application locally

```bash
# Install dependencies
uv sync

# Apply database migrations
uv run alembic upgrade head

# Build CSS (needed after changing classes in templates)
npm install
npm run css:build
# or in watch mode:
npm run css:watch

# Start the development server (port 8010)
uv run locus
# or directly via uvicorn with live reload:
uv run uvicorn locus.main:app --host 0.0.0.0 --port 8010 --reload
```

> [!NOTE]
> The compiled `src/locus/static/css/tailwind.css` is committed, so Node.js is not required to run the app. Rebuild it with `npm run css:build` after adding new Tailwind classes to templates or JS.

> [!NOTE]
> On first start against an empty database, an administrator account is created from `ADMIN_USERNAME` and `ADMIN_PASSWORD`. If those variables are not set, the first user created becomes the administrator.

> [!NOTE]
> Push notifications require HTTPS (browsers make an exception for `localhost` and `127.0.0.1` during development). On iOS they only work for a PWA added to the home screen (iOS 16.4+). Without VAPID keys the subscribe button is hidden and everything else works as usual.

### Running the tests

```bash
uv run pytest -v
```

## Running in Docker

The repository ships a `Dockerfile` that builds the app, applies migrations on start and listens on port `8000` (override with `PORT`). Base images are pinned by digest.

```bash
docker build -t locus .

# .env must sit next to it and contain production values
docker run -d --name locus -p 8000:8000 --env-file .env locus
```

At minimum you must set `DATABASE_URL` (PostgreSQL), `SECRET_KEY` (32+ characters), `ENVIRONMENT=production` and, if you want push notifications, a `VAPID_*` pair. The full template is `.env.example`.

> [!NOTE]
> Migrations run automatically inside the container (`alembic upgrade head`), no extra step needed.

> [!WARNING]
> `docker-compose.yml` starts **only** PostgreSQL with the login `admin` and the password `secret`, and exists for local development alone. Do not reuse these values in production.

## Public REST API

Locus exposes a REST API at `/api/v1` for external services, Telegram bots and automation scripts.

- **Authentication**: a long-lived API key (`Authorization: Bearer lk_...`) or a temporary session JWT (`POST /api/v1/auth/login`).
- **Key management**: an administrator issues and revokes API keys at `/admin/api-keys`, binding each key to a specific user. The key is shown only once, at creation.

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/auth/me` | The current authenticated user and their subgroup. |
| `GET` | `/api/v1/summary` | Daily summary (`?date=YYYY-MM-DD`): lessons with the attached homework. |
| `GET` | `/api/v1/schedule` | Lessons by weekday (`?day_of_week=1..6`). |
| `GET` | `/api/v1/homework` | Current assignments, filterable by date and subject. |
| `POST` | `/api/v1/homework` | Create an assignment (available to every authenticated user). |
| `PATCH` | `/api/v1/homework/{id}/status` | Update your personal status (`TODO` / `DONE`). |
| `GET` | `/api/v1/subjects` | Subjects with their classrooms and teachers. |
| `GET` | `/api/v1/vacations` | School vacation periods. |

> [!NOTE]
> The full request and response reference is in [docs/api.md](docs/api.md) (Russian). Interactive Swagger UI is available at `/docs` when `ENVIRONMENT=development`.

## Data and privacy

Locus contains no analytics and sends no data to the author of the project: everything stays in the database of your own instance.

**The instance owner** — whoever deploys and administers Locus — is the data controller: they are responsible for the lawful basis of processing, consents (especially for minors' data and teachers' phone numbers), retention periods, backups and the safety of encryption keys.

What is stored, who can see it, for how long and how it is deleted is described in [docs/privacy.md](docs/privacy.md) (Russian).

## Disclaimer

> [!WARNING]
> **Locus** is an independent project and is not affiliated with any official state or commercial education system. The software is provided "as is", without warranty of any kind — see the [MIT License](LICENSE). The author is not liable for inaccuracies in the schedule, missed deadlines, data loss or any other damage arising from the use of this project.
>
> The project is developed in free time. No support is provided and no response or fix deadlines are guaranteed. The instance owner is solely responsible for the security, availability, backups and personal data protection of their deployment.

## License

Distributed under the [MIT License](LICENSE).

Third-party components and their licenses are listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
