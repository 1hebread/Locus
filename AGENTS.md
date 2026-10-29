# AGENTS.md — Инструкция для ИИ-агентов в проекте Locus

Данный файл содержит исчерпывающее руководство по архитектуре, стеку технологий, правилам разработки и соглашениям проекта **Locus** для автономных и парных ИИ-агентов.

---

## 1. О проекте Locus

**Locus** — это быстрый селф-хостед электронный школьный онлайн-дневник с общим расписанием уроков, звонками и гибким трекером домашних заданий с персональными статусами выполнения.

### Ключевые возможности:
- **Единый дневник и расписание**: просмотр уроков по дням недели, время звонков, кабинеты, имена учителей, учет перемен. Расписание и предметы общие для всех пользователей школы/класса и управляются администратором (`is_admin`).
- **Общий пул ДЗ и персональный трекинг**: задания общие для всех пользователей (любой может добавлять, редактировать или удалять их), а статусы выполнения (`TODO` / `DONE`) хранятся персонально для каждого пользователя в таблице `homework_completions`.
- **PWA и мобильный фокус**: адаптивный интерфейс с чистым AMOLED-дизайном (`#000000`), плавными микроанимациями, динамической плавающей навигацией (Dock) и PWA-манифестом.
- **Гибридный рендеринг**: Server-Side Rendering (SSR) через Jinja2 + реактивные частичные обновления через HTMX без необходимости в тяжелых SPA-фреймворках.
- **Безопасность и администрирование**: JWT-аутентификация в защищенных HTTP-only cookies (для SSR) и в заголовках `Authorization: Bearer` (для REST API). Вход выполняется по логину. Публичной регистрации нет: пользователей создаёт и администрирует (смена паролей, удаление) администратор. Первый существующий пользователь становится админом, а для пустой базы админ создаётся из `ADMIN_USERNAME` / `ADMIN_PASSWORD`. Администратор не может удалить самого себя.

---

## 2. Стек технологий

- **Язык**: Python 3.12+ (поддерживается 3.14 / uv).
- **Web-фреймворк**: FastAPI (совмещает REST API `/api/v1` и SSR веб-роуты).
- **База данных и ORM**: SQLAlchemy 2.0 (строго асинхронный режим `AsyncSession`).
  - Разработка и тесты: SQLite (`aiosqlite`).
  - Production: PostgreSQL (`asyncpg`).
- **Миграции**: Alembic.
- **Валидация данных**: Pydantic v2 (`pydantic-settings`).
- **Шаблонизация и фронтенд**:
  - Jinja2 (HTML-шаблоны).
  - HTMX (частичные AJAX-свопы DOM без перезагрузки страниц).
  - Tailwind CSS (темная AMOLED-палитра).
  - Нативный Vanilla JavaScript (`src/locus/static/js/app.js`) для модалок, свайпов и Scroll Spy.
- **Пакетный менеджер**: `uv`.
- **Тестирование**: `pytest`, `pytest-asyncio`, `httpx`.

---

## 3. Структура репозитория

```text
.
├── alembic.ini                   # Конфигурация миграций Alembic
├── docker-compose.yml            # Docker-сборка (PostgreSQL + приложение)
├── migrations/                   # Скрипты миграций базы данных
│   └── versions/                 # Файлы версий схемы БД
├── pyproject.toml                # Зависимости и метаданные проекта
├── src/
│   └── locus/
│       ├── __init__.py
│       ├── main.py               # Точка входа приложения FastAPI, lifespan, статика
│       ├── config.py             # Настройки Pydantic Settings (.env)
│       ├── constants.py          # Константы (расписание звонков по умолчанию и т.д.)
│       ├── database.py           # AsyncEngine, async_sessionmaker, Base
│       ├── homework_status.py    # Хелперы персональных статусов (attach_statuses, set_status)
│       ├── homework_cleanup.py   # Автоочистка старых ДЗ (HOMEWORK_RETENTION_DAYS)
│       ├── lesson_suggestion.py  # Автоподстановка следующего урока
│       ├── security.py           # Хеширование паролей (bcrypt), генерация/валидация JWT
│       ├── templates_config.py   # Конфигурация Jinja2Templates и кастомных фильтров
│       ├── api/                  # REST API эндпоинты (/api/v1)
│       │   ├── auth.py           # Логин, получение текущего профиля
│       │   ├── deps.py           # FastAPI Dependencies (get_db, get_current_user, get_current_admin, get_current_admin_web)
│       │   ├── homework.py       # CRUD для общих домашних заданий и персональных статусов
│       │   ├── schedule.py       # Управление уроками расписания (только админ)
│       │   └── subjects.py       # Управление предметами (только админ)
│       ├── models/               # Модели SQLAlchemy 2.0
│       │   ├── user.py           # Модель User (id, username, hashed_password, is_admin, is_active)
│       │   ├── subject.py        # Модель Subject (id, name, teacher_name, room)
│       │   ├── lesson.py         # Модель Lesson (id, subject_id, day_of_week, lesson_number, bell_times...)
│       │   ├── homework.py       # Модель Homework (id, subject_id, lesson_id, title, due_date)
│       │   └── homework_completion.py # Модель HomeworkCompletion (id, homework_id, user_id, status)
│       ├── schemas/              # Pydantic-схемы запросов и ответов
│       │   ├── auth.py
│       │   ├── homework.py
│       │   ├── lesson.py
│       │   └── subject.py
│       ├── static/               # Статические ресурсы
│       │   ├── css/app.css       # Кастомные стили, анимации, скроллбары
│       │   ├── js/app.js         # Модалки, мобильный свайп недели, Scroll Spy
│       │   ├── manifest.json     # PWA манифест
│       │   └── sw.js             # Service Worker
│       ├── templates/            # Jinja2 HTML шаблоны
│       │   ├── base.html         # Базовый каркас (Sidebar для десктопа, Dock для мобайла)
│       │   ├── auth/             # Страница входа
│       │   ├── admin/            # Управление пользователями (только для админа)
│       │   ├── dashboard/        # Дневник (Desktop view, Mobile scroll, HTMX-фрагменты)
│       │   ├── homework/         # Раздел управления заданиями
│       │   ├── schedule/         # Конструктор расписания
│       │   └── subjects/         # Управление списком предметов
│       └── web/                  # SSR роуты (FastAPI + Jinja2 + HTMX)
│           ├── auth_routes.py
│           ├── admin_routes.py
│           ├── dashboard_routes.py
│           ├── homework_routes.py
│           ├── schedule_routes.py
│           └── subjects_routes.py
└── tests/                        # Тесты pytest
    ├── conftest.py               # Фикстуры: асинхронный тестовый клиент, тестовая БД в памяти
    ├── test_admin.py
    ├── test_auth.py
    ├── test_homework.py
    ├── test_homework_cleanup.py
    ├── test_schedule.py
    └── test_web.py
```

---

## 4. Команды разработки и соглашения Git

Все команды запускаются через `uv`:

```bash
# Установка зависимостей
uv sync

# Запуск локального сервера разработки (порт 8010)
uv run locus
# либо напрямую через uvicorn:
uv run uvicorn locus.main:app --host 0.0.0.0 --port 8010 --reload

# Запуск тестов
uv run pytest -v

# Применение миграций базы данных
uv run alembic upgrade head

# Создание новой миграции
uv run alembic revision --autogenerate -m "описание изменений"

# Проверка форматирования и отсутствия хвостовых пробелов
git diff --check
```

### Соглашения о коммитах (Git Commits)
- **Язык коммитов**: сообщения коммитов (`git commit`) оформляются **строго на английском языке** (English only).
- **Формат**: рекомендуется следовать спецификации Conventional Commits (`feat: ...`, `fix: ...`, `refactor: ...`, `chore: ...`).

---

## 5. Фронтенд-соглашения и специфика HTMX

### AMOLED Pure Black палитра
- Основной фон страницы и карточек уроков — чистый чёрный `#000000` (`bg-black`).
- Карточки отделяются от фона границей `border border-zinc-800/90` и контрастной тенью `shadow-[0_4px_20px_rgba(0,0,0,0.85)]`.
- Второстепенный текст, пустые состояния и подписи уроков оформляются в серых тонах: `text-zinc-400` / `text-zinc-500`.
- Акцентный цвет бренда — изумрудный (`text-emerald-400`, `bg-emerald-500`).

### Двухрежимный дашборд (Desktop vs Mobile)
В `dashboard/index.html` одновременно присутствуют две секции:
- **Desktop** (`hidden md:block`): классический переключатель дней недели сверху, просмотр по одному выбранному дню.
- **Mobile** (`md:hidden`): все дни недели рендерятся в едином вертикальном скролле со sticky-шапкой дней (`.sticky-mobile-week`), плавной прокруткой и scroll-spy подсветкой текущего дня.

### Важнейшие правила для HTMX-запросов
Из-за сосуществования десктопного и мобильного DOM-дерева на одной странице:
1. **Таргетинг только через `closest`**:
   - Категорически избегайте `hx-target="#hw-card-{{ hw.id }}"`, так как глобальный `querySelector` всегда перехватывает первое (десктопное) вхождение в DOM, ломая клики на мобильных.
2. **Параметры `view` при переключении ДЗ**:
   - `?view=compact` — возвращает лаконичную строку урока из [hw_compact_item.html](src/locus/templates/dashboard/hw_compact_item.html).
   - `?view=unassigned` — возвращает карточку нераспределенного ДЗ из [hw_unassigned_item.html](src/locus/templates/dashboard/hw_unassigned_item.html).
   - Без параметра — возвращает полную standalone-карточку из [homework/hw_item.html](src/locus/templates/homework/hw_item.html).
3. **Защита от двойного клика**:
   - На всех интерактивных кнопках переключения статуса обязательно должен присутствовать `hx-disabled-elt="this"`.
4. **Уникальность `id`**:
   - В DOM десктопные элементы получают префикс `id="desktop-..."`, а мобильные — `id="mobile-...-{{ day.day_num }}"`.

---

## 6. Бэкенд и база данных

1. **Асинхронность**:
   - Все эндпоинты, работающие с БД, должны быть строго асинхронными (`async def`).
   - Использование синхронных сессий SQLAlchemy запрещено.
2. **Общие сущности и персональные статусы**:
   - `Subject`, `Lesson` и `Homework` не содержат `user_id` и являются общими для всех пользователей.
   - Персональный статус выполнения ДЗ хранится в таблице `homework_completions` (пара `homework_id`, `user_id`).
   - Модель `Homework` не имеет колонки `status` в БД. Для передачи статуса в шаблоны и схемы Pydantic используется транзиентный атрибут `hw.status`, который выставляется через хелперы `attach_statuses(db, homework_list, user_id)` или `attach_status(db, hw, user_id)` из модуля `locus.homework_status`. Если записи о выполнении нет, статус считается `TODO`.
3. **Eager Loading связей**:
   - При выборке уроков или ДЗ всегда подгружайте связанные сущности через `selectinload(Lesson.subject)` или `selectinload(Homework.subject)`, чтобы избежать ошибки `MissingGreenlet` в асинхронном режиме при рендеринге шаблонов.
4. **Разграничение прав и безопасность**:
   - `get_current_user` / `get_current_user_web` — базовая аутентификация пользователя.
   - `get_current_admin` / `get_current_admin_web` — проверка прав администратора (`is_admin=True`). Не-админы не имеют доступа к созданию, обновлению и удалению предметов и расписания, а также к админ-панели управления пользователями (`/admin/users`).
   - Администратор не может удалить собственный аккаунт.
   - Аутентификация проверяет заголовок `Authorization: Bearer <token>`, а при его отсутствии извлекает токен из защищенной cookie (по умолчанию `locus_session`).
   - Пароли хешируются через `bcrypt`.

---

## 7. Особенности и проблемы iOS PWA (WebKit / Standalone)

При разработке интерфейса под установленные PWA на iOS (WebKit в режиме Standalone):
1. **Системный прогрессивный блюр / translucent scrim в строке состояния**:
   - В iOS WebKit при включенном `apple-mobile-web-app-capable: yes` операционная система принудительно накладывает градиентный блюр-слой (scrim) в верхней области экрана (Dynamic Island / Notch, ~44–59px).
   - Свойство `backdrop-filter: none` в CSS **не отключает** этот системный блюр, так как он рендерится композитором iOS поверх веб-вью.
   - Метатеги `apple-mobile-web-app-status-bar-style: black-translucent` или `black` расширяют размытую полосу вглубь шапки приложения, размывая заголовки и кнопки. Рекомендуется использовать `content="default"` в паре с `theme-color="#000000"`.
   - *Важно:* iOS кэширует метатеги манифеста в момент добавления приложения на экран «Домой» (Add to Home Screen). Изменение метатегов не применится, пока пользователь не переустановит ярлык PWA.
2. **Безопасные отступы (Safe Area) и защита от перекрытия**:
   - Все интерактивные элементы в прикрепленной (sticky/fixed) шапке должны быть опущены ниже зоны Dynamic Island и системного блюра с помощью запаса отступа: `padding-top: calc(env(safe-area-inset-top, 0px) + 1.25rem)`.
   - Фон шапки должен быть строго непрозрачным (`#000000`, 100% solid black). Использование полупрозрачности (`bg-black/95`) в сочетании с `backdrop-blur` вызывает визуальную грязь, двоение текста и мерцание при прокрутке в WebKit.
3. **Смещение якорного скролла (`scroll-margin-top`)**:
   - Для секций дней недели (`.mobile-day-section`) задается `scroll-margin-top: calc(env(safe-area-inset-top, 0px) + 7rem)` (класс `.scroll-mt-safe`), чтобы при программном переходе к выбранному дню его заголовок не прятался под зафиксированной верхней панелью.
