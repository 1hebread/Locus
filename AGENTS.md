# AGENTS.md — Instructions for AI Agents in the Locus Project

This file provides comprehensive guidelines on architecture, technology stack, development rules, and conventions for the **Locus** project, intended for autonomous and pair-programming AI agents.

---

## 1. About the Locus Project

**Locus** is a fast, self-hosted online school electronic planner/diary featuring a shared lesson schedule, bell timetables, and a flexible homework tracker with personal completion statuses.

### Key Features:
- **Unified Diary and Schedule**: view lessons by day of the week, bell times, classrooms, teacher names, and recess intervals. The schedule and subjects are shared across all users in a school/class and managed by an administrator (`is_admin`).
- **Shared Homework Pool & Personal Tracking**: assignments are shared across all users (anyone can add, edit, or delete them), while completion statuses (`TODO` / `DONE`) are tracked individually per user in the `homework_completions` table.
- **Homework Audit Log**: assignment creation, edits, and deletions are logged in `homework_events` (who, when, and which fields changed). Lesson modals display the last editor, and the full history is accessible to admins at `/admin/history`.
- **Push Notifications (Web Push)**: homework creation, edits, and deletions are pushed to subscribed browsers/PWAs (to all active users except the author, respecting subgroups). Subscriptions are stored in `push_subscriptions`, and VAPID keys are configured via `VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY` (generation: `uv run locus-vapid`). Without keys, push notifications are disabled.
- **Public API**: REST `/api/v1` with JWT or API key (`Authorization: Bearer lk_…`), documentation: `docs/api.md` (Swagger `/docs` is only available in development). Keys are created by admins at `/admin/api-keys` and act on behalf of the selected user; daily summary is available at `GET /api/v1/summary?date=YYYY-MM-DD`.
- **PWA & Mobile-First Focus**: responsive UI with pure AMOLED black design (`#000000`), smooth micro-animations, a dynamic floating navigation dock, and a PWA manifest.
- **Hybrid Rendering**: Server-Side Rendering (SSR) via Jinja2 + reactive partial updates via HTMX without requiring heavy SPA frameworks.
- **Security & Administration**: JWT authentication via secure HTTP-only cookies (for SSR) and `Authorization: Bearer` headers (for REST API). Login is username-based. There is no public registration: users are created and managed (password changes, deletion) by an administrator. The first existing user automatically becomes an admin; for a fresh database, an admin user is seeded from `ADMIN_USERNAME` / `ADMIN_PASSWORD`. Administrators cannot delete their own account.

---

## 2. Technology Stack

- **Language**: Python 3.12+ (supports 3.14 / uv).
- **Web Framework**: FastAPI (combines REST API `/api/v1` and SSR web routes).
- **Database & ORM**: SQLAlchemy 2.0 (strictly asynchronous `AsyncSession`).
  - Development & Tests: SQLite (`aiosqlite`).
  - Production: PostgreSQL (`asyncpg`).
- **Migrations**: Alembic.
- **Data Validation**: Pydantic v2 (`pydantic-settings`).
- **Templating & Frontend**:
  - Jinja2 (HTML templates).
  - HTMX (partial DOM AJAX swaps without full-page reloads).
  - Tailwind CSS (AMOLED dark palette).
  - Vanilla JavaScript (`src/locus/static/js/app.js`) for modals, swipes, and Scroll Spy.
- **Package Manager**: `uv`.
- **Testing**: `pytest`, `pytest-asyncio`, `httpx`.

---

## 3. Repository Structure

```text
.
├── alembic.ini                   # Alembic migration configuration
├── docker-compose.yml            # Docker Compose setup (PostgreSQL + application)
├── migrations/                   # Database migration scripts
│   └── versions/                 # Database schema revisions
├── pyproject.toml                # Project metadata and dependencies
├── src/
│   └── locus/
│       ├── __init__.py
│       ├── main.py               # FastAPI entrypoint, lifespan, static file mounting
│       ├── config.py             # Pydantic Settings configuration (.env)
│       ├── constants.py          # Constants (default bell schedule, etc.)
│       ├── database.py           # AsyncEngine, async_sessionmaker, Base
│       ├── homework_status.py    # Personal status helpers (attach_statuses, set_status)
│       ├── homework_audit.py     # Homework audit log (create/edit/delete tracking)
│       ├── homework_cleanup.py   # Automatic cleanup for old homework (HOMEWORK_RETENTION_DAYS)
│       ├── lesson_suggestion.py  # Next lesson auto-suggestion
│       ├── push.py               # Web Push notifications for homework changes (background tasks)
│       ├── vapid.py              # VAPID key generation (`uv run locus-vapid`)
│       ├── security.py           # Password hashing (bcrypt), JWT, API key generation/hashing
│       ├── templates_config.py   # Jinja2Templates configuration and custom filters
│       ├── api/                  # REST API endpoints (/api/v1)
│       │   ├── auth.py           # Login, current profile endpoint
│       │   ├── deps.py           # FastAPI Dependencies (get_db, get_current_user, get_current_admin, get_current_admin_web)
│       │   ├── homework.py       # CRUD for shared homework and personal statuses
│       │   ├── schedule.py       # Schedule lesson management (admin only)
│       │   ├── subjects.py       # Subject management (admin only)
│       │   ├── summary.py        # Daily summary: lessons + associated homework (/api/v1/summary)
│       │   └── vacations.py      # Vacations
│       ├── models/               # SQLAlchemy 2.0 models
│       │   ├── user.py           # User model (id, username, hashed_password, is_admin, is_active)
│       │   ├── subject.py        # Subject model (id, name, teacher_name, room)
│       │   ├── lesson.py         # Lesson model (id, subject_id, day_of_week, lesson_number, bell_times...)
│       │   ├── homework.py       # Homework model (id, subject_id, lesson_id, title, due_date)
│       │   ├── homework_completion.py # HomeworkCompletion model (id, homework_id, user_id, status)
│       │   ├── homework_event.py # HomeworkEvent model (homework change audit log)
│       │   ├── push_subscription.py # PushSubscription model (browser/PWA subscription)
│       │   └── api_key.py        # ApiKey model (key hash, bound to a user)
│       ├── schemas/              # Pydantic request and response schemas
│       │   ├── auth.py
│       │   ├── homework.py
│       │   ├── lesson.py
│       │   ├── subject.py
│       │   ├── summary.py
│       │   └── vacation.py
│       ├── static/               # Static assets
│       │   ├── css/app.css       # Custom styles, animations, scrollbars
│       │   ├── js/app.js         # Modals, mobile week swipe, Scroll Spy
│       │   ├── manifest.json     # PWA manifest
│       │   └── sw.js             # Service Worker
│       ├── templates/            # Jinja2 HTML templates
│       │   ├── base.html         # Base layout (Sidebar for desktop, Dock for mobile)
│       │   ├── auth/             # Login page
│       │   ├── admin/            # Users, change history, API keys (admin only)
│       │   ├── dashboard/        # Dashboard (Desktop view, Mobile scroll, HTMX fragments)
│       │   ├── homework/         # Homework management section
│       │   ├── schedule/         # Schedule constructor
│       │   └── subjects/         # Subject list management
│       └── web/                  # SSR routes (FastAPI + Jinja2 + HTMX)
│           ├── auth_routes.py
│           ├── admin_routes.py
│           ├── dashboard_routes.py
│           ├── homework_routes.py
│           ├── push_routes.py    # Web Push subscribe/unsubscribe and VAPID key delivery
│           ├── schedule_routes.py
│           └── subjects_routes.py
└── tests/                        # Pytest tests
    ├── conftest.py               # Fixtures: async test client, in-memory test database
    ├── test_admin.py
    ├── test_api_keys.py
    ├── test_auth.py
    ├── test_homework.py
    ├── test_homework_audit.py
    ├── test_homework_cleanup.py
    ├── test_push.py
    ├── test_schedule.py
    └── test_web.py
```

---

## 4. Development Commands and Git Conventions

All commands are run using `uv`:

```bash
# Install dependencies
uv sync

# Run local development server (port 8010)
uv run locus
# or directly via uvicorn:
uv run uvicorn locus.main:app --host 0.0.0.0 --port 8010 --reload

# Run tests
uv run pytest -v

# Apply database migrations
uv run alembic upgrade head

# Create a new migration
uv run alembic revision --autogenerate -m "description of changes"

# Check formatting and trailing whitespace
git diff --check
```

### Git Commit Conventions
- **Commit Language**: commit messages (`git commit`) must be written **strictly in English**.
- **Format**: follow the Conventional Commits specification (`feat: ...`, `fix: ...`, `refactor: ...`, `chore: ...`).

---

## 5. Frontend Conventions and HTMX Specifics

### AMOLED Pure Black Palette
- Primary background of pages and lesson cards: pure black `#000000` (`bg-black`).
- Cards are separated from the background with a border `border border-zinc-800/90` and contrast shadow `shadow-[0_4px_20px_rgba(0,0,0,0.85)]`.
- Secondary text, empty states, and lesson captions are styled in gray tones: `text-zinc-400` / `text-zinc-500`.
- Brand accent color: emerald (`text-emerald-400`, `bg-emerald-500`).

### Dual-Mode Dashboard (Desktop vs Mobile)
In `dashboard/index.html`, two sections coexist simultaneously:
- **Desktop** (`hidden md:block`): traditional weekday tabs at the top, viewing one selected day at a time.
- **Mobile** (`md:hidden`): all weekdays rendered in a single vertical scroll with a sticky day header (`.sticky-mobile-week`), smooth scrolling, and scroll-spy active day highlighting.

### Critical Rules for HTMX Requests
Due to both desktop and mobile DOM trees coexisting on the same page:
1. **Targeting via `closest` only**:
   - Strictly avoid `hx-target="#hw-card-{{ hw.id }}"`, because a global `querySelector` will always match the first (desktop) instance in the DOM, breaking interactions on mobile.
2. **`view` parameter when toggling homework status**:
   - `?view=compact` — returns a compact lesson row from [hw_compact_item.html](src/locus/templates/dashboard/hw_compact_item.html).
   - `?view=unassigned` — returns an unassigned homework card from [hw_unassigned_item.html](src/locus/templates/dashboard/hw_unassigned_item.html).
   - Without parameter — returns a full standalone card from [homework/hw_item.html](src/locus/templates/homework/hw_item.html).
3. **Double-click Protection**:
   - All interactive status-toggling buttons must include `hx-disabled-elt="this"`.
4. **Unique `id`s**:
   - In the DOM, desktop elements use the prefix `id="desktop-..."`, while mobile elements use `id="mobile-...-{{ day.day_num }}"`.

---

## 6. Backend and Database

1. **Asynchronous Execution**:
   - All endpoints interacting with the database must be strictly asynchronous (`async def`).
   - Using synchronous SQLAlchemy sessions is forbidden.
2. **Shared Entities and Personal Statuses**:
   - `Subject`, `Lesson`, and `Homework` do not have a `user_id` column and are shared across all users.
   - Personal homework completion statuses are stored in the `homework_completions` table (`homework_id`, `user_id` pair).
   - The `Homework` model has no `status` column in the database. To pass statuses to templates and Pydantic schemas, use the transient attribute `hw.status`, populated via the `attach_statuses(db, homework_list, user_id)` or `attach_status(db, hw, user_id)` helpers from `locus.homework_status`. If no completion record exists, the status defaults to `TODO`.
3. **Eager Loading of Relationships**:
   - When querying lessons or homework, always eagerly load related entities via `selectinload(Lesson.subject)` or `selectinload(Homework.subject)` to avoid `MissingGreenlet` errors in async mode during template rendering.
4. **Access Control & Security**:
   - `get_current_user` / `get_current_user_web` — base user authentication.
   - `get_current_admin` / `get_current_admin_web` — administrator privileges check (`is_admin=True`). Non-admin users cannot create, update, or delete subjects and schedule lessons, nor access the admin user management panel (`/admin/users`).
   - Administrators cannot delete their own account.
   - Authentication checks the `Authorization: Bearer <token>` header first; if absent, it extracts the token from a secure cookie (`locus_session` by default).
   - Passwords are hashed using `bcrypt`.

---

## 7. iOS PWA Nuances and Quirks (WebKit / Standalone)

When developing the UI for standalone installed PWAs on iOS (WebKit Standalone mode):
1. **System Progressive Blur / Translucent Scrim in Status Bar**:
   - In iOS WebKit with `apple-mobile-web-app-capable: yes` enabled, the operating system forcibly overlays a gradient blur layer (scrim) across the top screen area (Dynamic Island / Notch, ~44–59px).
   - Setting `backdrop-filter: none` in CSS **does not** disable this system blur, as it is rendered by the iOS compositor above the web view.
   - The meta tags `apple-mobile-web-app-status-bar-style: black-translucent` or `black` expand the blurred region deeper into the application header, blurring headers and buttons. It is recommended to use `content="default"` paired with `theme-color="#000000"`.
   - *Important:* iOS caches manifest meta tags when the app is added to the home screen ("Add to Home Screen"). Any changes to these meta tags will not take effect until the user reinstalls the PWA shortcut.
2. **Safe Area Insets and Overlap Protection**:
   - All interactive elements in sticky/fixed headers must be positioned below the Dynamic Island / system blur area using padding: `padding-top: calc(env(safe-area-inset-top, 0px) + 1.25rem)`.
   - The header background must be 100% solid black (`#000000`). Using semi-transparency (`bg-black/95`) combined with `backdrop-blur` causes visual artifacts, double text rendering, and flickering during scrolling in WebKit.
3. **Anchor Scroll Offset (`scroll-margin-top`)**:
   - For weekday sections (`.mobile-day-section`), specify `scroll-margin-top: calc(env(safe-area-inset-top, 0px) + 7rem)` (via `.scroll-mt-safe`) so that programmatic scrolling to a selected day does not hide its header beneath the fixed top bar.
