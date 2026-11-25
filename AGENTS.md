# AGENTS.md — Instructions for AI Agents in the Locus Project

This file provides comprehensive guidelines on architecture, technology stack, development rules, and conventions for the **Locus** project, intended for autonomous and pair-programming AI agents.

---

## 1. About the Locus Project

**Locus** is a fast, self-hosted online school electronic planner/diary featuring a shared lesson schedule, bell timetables, and a flexible homework tracker with personal completion statuses.

### Key Features:
- **Unified Diary and Schedule**: view lessons by day of the week, bell times, classrooms, teacher names, and recess intervals. The schedule and subjects are shared across all users in a school/class and managed by an administrator (`is_admin`).
- **Shared Homework Pool & Personal Tracking**: assignments are shared across all users (anyone can add, edit, or delete them), while completion statuses (`TODO` / `DONE`) are tracked individually per user in the `homework_completions` table.
- **Homework Audit Log**: assignment creation, edits, and deletions are logged in `homework_events` (who, when, and which fields changed). Lesson modals display the last editor, and the full history is accessible to admins at `/admin/history`.
- **Duty Roster**: `/duty` shows who is on duty for each school weekday (Monday to Saturday). Entries are plain lines of text; `Иван И. (ivan)` binds a line to the user with that login, and the current user's own line is highlighted on today's card. The roster text is encrypted at rest with Fernet, like teacher names and phones. Only administrators can edit the roster. Also available via `GET /api/v1/duty`, editing via `PUT /api/v1/duty/{day_of_week}` (admin only).
- **Attendance**: `/attendance` shows the class roster and one day's attendance. The roster is a plain textarea of full names (one per line), sorted alphabetically; full names are encrypted at rest with Fernet. Names removed from the list are archived (`students.is_active = False`) rather than deleted, so their past marks stay visible. Marks are day-level: `PRESENT`, `TRUANT`, `LATE`, `EXCUSED`, `SICK`, plus the absence variants `ABSENT_UNKNOWN` and `LEFT` (the "Нет" button opens a submenu with all three absence marks; the variants count in `absent`); no record means "not marked". The count cards filter the list by status, and the "Остальные: Был" button marks every unmarked active student as present. A copy button next to it copies the absent students as `ФИО — причина` lines (truant, sick, excused, left, unknown). Every authenticated user can view the page, while only headmen (`is_headman`) and admins can edit the roster and marks. Marks are allowed on school days (Monday–Saturday) that are not in the future and do not overlap vacations. Clicking the same status again clears the mark. A daily cleanup deletes attendance marks older than `HOMEWORK_RETENTION_DAYS` and then removes archived students that have no marks left. Also available via `GET /api/v1/attendance?date=YYYY-MM-DD` (read for everyone) and `PUT /api/v1/attendance/{date}` (headman/admin only).
- **Push Notifications (Web Push)**: homework creation, edits, and deletions are pushed to subscribed browsers/PWAs (to all active users except the author, respecting subgroups). Subscriptions are stored in `push_subscriptions`, and VAPID keys are configured via `VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY` (generation: `uv run locus-vapid`). Without keys, push notifications are disabled.
- **Public API**: REST `/api/v1` with JWT or API key (`Authorization: Bearer lk_…`), documentation: `docs/api.md` (Swagger `/docs` is only available in development). Keys are created by admins at `/admin/api-keys` and act on behalf of the selected user; daily summary is available at `GET /api/v1/summary?date=YYYY-MM-DD`.
- **PWA & Mobile-First Focus**: responsive UI with dark (pure black), light and two pixel-art themes, smooth micro-animations, a dynamic floating navigation dock, and a PWA manifest. Theme is chosen per user in `/settings` (dark, light, system, pixel dark, pixel light).
- **Hybrid Rendering**: Server-Side Rendering (SSR) via Jinja2 + reactive partial updates via HTMX without requiring heavy SPA frameworks.
- **Security & Administration**: JWT authentication via secure HTTP-only cookies (for SSR) and `Authorization: Bearer` headers (for REST API). Login is username-based. There is no public registration: users are created and managed (password changes, deletion) by an administrator. The first existing user automatically becomes an admin; for a fresh database, an admin user is seeded from `ADMIN_USERNAME` / `ADMIN_PASSWORD`. Administrators cannot delete their own account.

---

## 2. Technology Stack

- **Language**: Python 3.12+ (supports 3.15 / uv).
- **Web Framework**: FastAPI (combines REST API `/api/v1` and SSR web routes).
- **Database & ORM**: SQLAlchemy 2.0 (strictly asynchronous `AsyncSession`).
  - Development & Tests: SQLite (`aiosqlite`).
  - Production: PostgreSQL (`asyncpg`).
- **Migrations**: Alembic.
- **Data Validation**: Pydantic v2 (`pydantic-settings`).
- **Templating & Frontend**:
  - Jinja2 (HTML templates).
  - HTMX (partial DOM AJAX swaps without full-page reloads).
  - Tailwind CSS (themeable semantic palette, dark/light).
  - Vanilla JavaScript (`src/locus/static/js/app.js`) for modals, swipes, and Scroll Spy.
- **Package Manager**: `uv`.
- **Testing**: `pytest`, `pytest-asyncio`, `httpx`.

---

## 3. Repository Structure

```text
.
├── alembic.ini                   # Alembic migration configuration
├── Dockerfile                    # Production image (pinned base images)
├── .github/
│   └── workflows/ci.yml          # CI: uv sync + pytest on Python 3.12–3.15
├── docker-compose.yml            # Local PostgreSQL for development
├── render.yaml                   # Render Blueprint example
├── migrations/                   # Database migration scripts
│   └── versions/                 # Database schema revisions
├── docs/
│   ├── api.md                    # REST API reference
│   └── privacy.md                # Privacy policy template for instance owners
├── pyproject.toml                # Project metadata and dependencies
├── .env.example                  # Environment variable template
├── src/
│   └── locus/
│       ├── __init__.py
│       ├── main.py               # FastAPI entrypoint, lifespan, static file mounting
│       ├── config.py             # Pydantic Settings configuration (.env)
│       ├── constants.py          # Constants (default bell schedule, etc.)
│       ├── database.py           # AsyncEngine, async_sessionmaker, Base
│       ├── crypto.py             # Fernet encryption for teacher names/phones, duty roster text and student names
│       ├── rate_limiter.py       # Login and API rate limiting
│       ├── schedule_service.py   # Lesson cloning and schedule helpers
│       ├── schedule_validation.py # Lesson payload validation
│       ├── subgroup_helpers.py   # Subgroup parsing and matching
│       ├── homework_status.py    # Personal status helpers (attach_statuses, set_status)
│       ├── homework_rules.py     # Homework business rules (one assignment per lesson+date)
│       ├── duty.py               # Duty roster parsing, day loading and upsert
│       ├── attendance.py         # Class roster sync, attendance day building and mark upsert
│       ├── homework_audit.py     # Homework audit log (create/edit/delete tracking)
│       ├── homework_cleanup.py   # Automatic cleanup for old homework (HOMEWORK_RETENTION_DAYS)
│       ├── attendance_cleanup.py # Retention cleanup for attendance and empty archived students
│       ├── lesson_suggestion.py  # Next lesson auto-suggestion
│       ├── push.py               # Web Push notifications for homework changes (background tasks)
│       ├── vapid.py              # VAPID key generation (`uv run locus-vapid`)
│       ├── security.py           # Password hashing (bcrypt), JWT, API key generation/hashing
│       ├── templates_config.py   # Jinja2Templates configuration and custom filters
│       ├── api/                  # REST API endpoints (/api/v1)
│       │   ├── auth.py           # Login, current profile endpoint
│       │   ├── deps.py           # FastAPI Dependencies (get_db, get_current_user, get_current_admin, get_current_admin_web, get_current_headman, get_current_headman_web)
│       │   ├── duty.py           # Duty roster: read for everyone, edit for admins
│       │   ├── attendance.py     # Class roster and day attendance: read for everyone, edit for headman/admin
│       │   ├── homework.py       # CRUD for shared homework and personal statuses
│       │   ├── schedule.py       # Schedule lesson management (admin only)
│       │   ├── subjects.py       # Subject management (admin only)
│       │   ├── summary.py        # Daily summary: lessons + associated homework (/api/v1/summary)
│       │   └── vacations.py      # Vacations
│       ├── models/               # SQLAlchemy 2.0 models
│       │   ├── user.py           # User model (id, username, hashed_password, is_admin, is_headman, is_active, theme)
│       │   ├── subject.py        # Subject model (id, name, teacher_name, room)
│       │   ├── lesson.py         # Lesson model (id, subject_id, day_of_week, lesson_number, bell_times...)
│       │   ├── homework.py       # Homework model (id, subject_id, lesson_id, title, due_date)
│       │   ├── homework_completion.py # HomeworkCompletion model (id, homework_id, user_id, status)
│       │   ├── homework_event.py # HomeworkEvent model (homework change audit log)
│       │   ├── push_subscription.py # PushSubscription model (browser/PWA subscription)
│       │   ├── api_key.py        # ApiKey model (key hash, bound to a user)
│       │   ├── vacation.py       # Vacation periods
│       │   ├── duty_day.py       # DutyDay model (encrypted duty roster text per weekday)
│       │   ├── student.py        # Student model (encrypted class roster full name, archived flag)
│       │   └── attendance.py     # AttendanceRecord model (student + date + status)
│       ├── schemas/              # Pydantic request and response schemas
│       │   ├── auth.py
│       │   ├── attendance.py
│       │   ├── duty.py
│       │   ├── homework.py
│       │   ├── lesson.py
│       │   ├── subject.py
│       │   ├── summary.py
│       │   └── vacation.py
│       ├── static/               # Static assets
│       │   ├── css/app.css       # Custom styles, animations, scrollbars
│       │   ├── css/tailwind.css  # Compiled Tailwind build (committed)
│       │   ├── css/tailwind.src.css # Tailwind source compiled by npm
│       │   ├── icons/            # PWA icons (SVG + PNG, C2PA metadata stripped)
│       │   ├── fonts/            # Pixeloid Sans Bold woff2 (OFL 1.1) for the pixel themes
│       │   ├── js/app.js         # Modals, mobile week swipe, Scroll Spy
│       │   ├── js/htmx.min.js    # Vendored HTMX 2.0.4 (0BSD)
│       │   ├── manifest.json     # PWA manifest
│       │   └── sw.js             # Service Worker
│       ├── templates/            # Jinja2 HTML templates
│       │   ├── base.html         # Base layout (Sidebar for desktop, Dock for mobile)
│       │   ├── auth/             # Login page
│       │   ├── admin/            # Users, change history, API keys (admin only)
│       │   ├── dashboard/        # Dashboard (Desktop view, Mobile scroll, HTMX fragments)
│       │   ├── homework/         # Homework management section
│       │   ├── duty/             # Duty roster per weekday
│       │   ├── attendance/       # Class roster and per-day attendance grid
│       │   ├── schedule/         # Schedule constructor
│       │   ├── settings/         # Theme and appearance settings
│       │   └── subjects/         # Subject list management
│       └── web/                  # SSR routes (FastAPI + Jinja2 + HTMX)
│           ├── auth_routes.py
│           ├── admin_routes.py
│           ├── dashboard_routes.py
│           ├── homework_routes.py
│           ├── push_routes.py    # Web Push subscribe/unsubscribe and VAPID key delivery
│           ├── duty_routes.py    # Duty roster page and admin editing
│           ├── attendance_routes.py # Attendance page, roster textarea and HTMX mark toggle
│           ├── schedule_routes.py
│           ├── settings_routes.py # Settings page, theme preference (POST /settings/theme)
│           └── subjects_routes.py
└── tests/                        # Pytest tests
    ├── conftest.py               # Fixtures: async test client, in-memory test database
    ├── helpers.py                # Shared test factories
    ├── test_admin.py
    ├── test_api_keys.py
    ├── test_attendance.py
    ├── test_attendance_cleanup.py
    ├── test_auth.py
    ├── test_duty.py
    ├── test_homework.py
    ├── test_homework_audit.py
    ├── test_homework_cleanup.py
    ├── test_lesson_suggestion.py
    ├── test_push.py
    ├── test_schedule.py
    ├── test_settings.py
    ├── test_subgroups.py
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

# Rebuild the committed Tailwind build (required after adding new utility classes)
npm run css:build

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
- **Body**: only for large changes; small commits need nothing beyond the subject line. For a larger change, write a short bullet list of what it includes, one line per change.

### Documentation Sync
- If a change touches a documented area, update the docs in the same change. This includes `AGENTS.md` (structure, modules, conventions), `docs/api.md` (endpoints, fields, limits, error codes), `.env.example` (new settings) and `docs/privacy.md` (data storage/privacy).
- Do not leave documentation describing behavior that no longer exists: stale docs are worse than missing ones.

---

## 5. Frontend Conventions and HTMX Specifics

### Theming and Palette
- All colors come from semantic Tailwind tokens that map to CSS variables in `app.css`: `surface-*`, `edge-*`, `fg-*`, `accent-*`, `danger-*`, `warning-ink`, `info-*`, `on-accent`; shadows via `shadow-card` / `shadow-glow`.
- Palettes live in `:root` (dark, pure black `#000000`), `html[data-theme="light"]`, `html[data-theme="pixel-dark"]` and `html[data-theme="pixel-light"]`. Do not hard-code `zinc-*` / `emerald-*` / hex colors in templates: use tokens. The fixed green `brand-*` is only for the week ribbon and gradient headers.
- Pixel themes keep the same tokens but add hard chrome via `html[data-theme^="pixel-"]`: square corners, chunky input borders, stepped 4px `border-image` frames on cards/modals and hard offset shadows.
- Theme preference (`dark`, `light`, `system`, `pixel-dark`, `pixel-light`) is stored in `users.theme` and rendered as `data-theme-pref`; `data-theme` holds the resolved choice (`dark` / `light` / pixel values) and is applied by an inline script in `base.html` before CSS loads. Guests and new users default to `system`.
- Switching: radios `[data-theme-choice]` on `/settings` call `applyThemePreference()` (250 ms color transition, no page reload) and persist via `POST /settings/theme` (JSON `{"theme": "..."}`, `204`); failures roll the selection back.

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
   - A lesson can hold only one assignment per due date. The web form and REST API reject duplicates with `409 Conflict` via `lesson_homework_exists` from `locus.homework_rules`, and the partial unique index `uq_homeworks_lesson_due_date` (`lesson_id`, `due_date`; unassigned rows exempt) is the real guarantee; the dashboard lesson modal reuses the existing row instead of creating another.
3. **Eager Loading of Relationships**:
   - When querying lessons or homework, always eagerly load related entities via `selectinload(Lesson.subject)` or `selectinload(Homework.subject)` to avoid `MissingGreenlet` errors in async mode during template rendering.
4. **Access Control & Security**:
   - `get_current_user` / `get_current_user_web` — base user authentication.
   - `get_current_admin` / `get_current_admin_web` — administrator privileges check (`is_admin=True`). Non-admin users cannot create, update, or delete subjects and schedule lessons, nor access the admin user management panel (`/admin/users`).
   - `get_current_headman` / `get_current_headman_web` — class-representative check (`is_headman=True` or `is_admin=True`). Used for attendance marks and roster edits. The flag is toggled by an administrator on `/admin/users` and exposed in `GET /api/v1/auth/me`.
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
