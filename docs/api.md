# Locus API

REST API дневника: расписание, домашние задания, предметы, каникулы и сводка на день.

- База: `https://<ваш-домен>/api/v1`
- Формат: JSON, кодировка UTF-8
- Интерактивная схема (Swagger) доступна только в development: `/docs`. В production она отключена (404).

## Авторизация

Запросы авторизуются API-ключом:

```
Authorization: Bearer lk_...
```

Ключ создаётся администратором в веб-интерфейсе на `/admin/api-keys`: указывается название и пользователь, от имени которого ключ работает. Ключ показывается один раз, в базе хранится только его хеш. Отзыв ключа — там же; после отзыва запросы получают `401`.

Ключ наследует права пользователя: подгруппу, доступ к админским операциям, а также возможность записи (создание, правка и удаление ДЗ). Если ключ не нужен для записи — не давайте его посторонним.

Изменения ДЗ, сделанные через ключ, в журнале администратора (`/admin/history`) помечаются именем ключа: `student (Telegram-бот)`. Обычным пользователям это не показывается.

Альтернатива: `POST /auth/login` с логином и паролем возвращает JWT на 7 дней. Для ботов предпочтительнее ключ.

### Ошибки

| Код | Значение |
|-----|----------|
| 400 | Некорректные данные (например, ДЗ на воскресенье) |
| 401 | Нет ключа, ключ неверный или отозван |
| 403 | Недостаточно прав (чужой урок, чужое ДЗ, не админ) |
| 404 | Объект не найден |
| 422 | Ошибка валидации полей |
| 429 | Слишком много неудачных попыток входа (только `/auth/login`) |

Тело ошибки: `{"detail": "текст"}`.

## Быстрый старт

```bash
KEY="lk_..."

# Кто я
curl -H "Authorization: Bearer $KEY" https://example.com/api/v1/auth/me

# Что задано на сегодня
curl -H "Authorization: Bearer $KEY" https://example.com/api/v1/summary

# Расписание на понедельник
curl -H "Authorization: Bearer $KEY" "https://example.com/api/v1/schedule?day_of_week=1"
```

## Эндпоинты

### Профиль

`GET /auth/me` — текущий пользователь.

```json
{
  "id": 1,
  "username": "root",
  "is_active": true,
  "is_admin": true,
  "subgroup": null,
  "created_at": "2026-10-01T12:00:00Z"
}
```

### Сводка на день

`GET /summary?date=YYYY-MM-DD` — уроки на день с привязанными ДЗ. Без `date` — сегодня. Удобно для напоминаний.

- На каникулах `lessons` пустой, все ДЗ на этот день попадают в `unassigned_homework`.
- ДЗ привязывается по `lesson_id`; если урок не указан — к уроку того же предмета с учётом подгруппы.

```json
{
  "date": "2026-11-02",
  "day_of_week": 1,
  "day_name": "Понедельник",
  "vacation": null,
  "lessons": [
    {
      "lesson_number": 1,
      "start_time": "08:00",
      "end_time": "08:45",
      "room": "304",
      "teacher_name": "Иванова С.П.",
      "subgroup": null,
      "subject": { "id": 1, "name": "Алгебра", "room": "304", "...": "..." },
      "homework": [
        {
          "id": 12,
          "subject_id": 1,
          "lesson_id": 3,
          "title": "№ 123, 124",
          "due_date": "2026-11-02",
          "subgroup": null,
          "status": "TODO",
          "created_at": "2026-10-29T09:00:00Z",
          "updated_at": "2026-10-29T09:00:00Z",
          "subject": { "...": "..." }
        }
      ]
    }
  ],
  "unassigned_homework": []
}
```

### Расписание

`GET /schedule` — все уроки. Параметры:

| Параметр | Тип | Описание |
|----------|-----|----------|
| `day_of_week` | 1–7 | 1 = понедельник |
| `week_type` | `ALL` / `NUMERATOR` / `DENOMINATOR` | числитель/знаменатель; `ALL` — без фильтра |
| `subgroup` | 1–2 | только для админа; ученик всегда видит свою подгруппу и общие уроки |

`GET /schedule/{id}` — один урок.

```json
{
  "id": 3,
  "subject_id": 1,
  "day_of_week": 1,
  "lesson_number": 1,
  "start_time": "08:00",
  "end_time": "08:45",
  "week_type": "ALL",
  "room": null,
  "note": null,
  "subgroup": null,
  "subject": { "id": 1, "name": "Алгебра", "teacher_name": "Иванова С.П.", "...": "..." }
}
```

`room` и `note` в уроке — переопределения; если `null`, кабинет берётся из `subject.room`.

### Домашние задания

`GET /homework` — общий пул ДЗ с персональным статусом текущего пользователя.

| Параметр | Тип | Описание |
|----------|-----|----------|
| `status` | `TODO` / `IN_PROGRESS` / `DONE` | персональный статус |
| `subject_id` | int | предмет |
| `due_date` | `YYYY-MM-DD` | ровно на дату |
| `due_from`, `due_to` | `YYYY-MM-DD` | диапазон сдачи |
| `subgroup` | 1–2 | только для админа |

`GET /homework/{id}` — одно задание.

```json
{
  "id": 12,
  "subject_id": 1,
  "lesson_id": 3,
  "title": "№ 123, 124",
  "due_date": "2026-11-02",
  "subgroup": null,
  "status": "TODO",
  "created_at": "2026-10-29T09:00:00Z",
  "updated_at": "2026-10-29T09:00:00Z",
  "subject": { "id": 1, "name": "Алгебра", "...": "..." }
}
```

`POST /homework` — создать задание (201).

```json
{
  "subject_id": 1,
  "lesson_id": 3,
  "title": "№ 123, 124",
  "due_date": "2026-11-02",
  "subgroup": null,
  "status": "TODO"
}
```

`PUT /homework/{id}` — изменить переданные поля (можно и `status`).

`PATCH /homework/{id}/status` — только персональный статус: `{"status": "DONE"}`.

`DELETE /homework/{id}` — удалить (204).

Ограничения:
- нельзя ставить срок на воскресенье;
- на один урок — только одно задание на дату: повторное создание или перенос ДЗ на занятую пару «урок + дата» возвращает `409 Conflict`;
- ученик может работать только с ДЗ своей подгруппы и общими;
- подгруппа задания должна совпадать с подгруппой урока;
- `status` — персональная отметка, она не меняет задание у других.

### Предметы

`GET /subjects` — все предметы (по алфавиту). `GET /subjects/{id}` — один.

```json
{
  "id": 1,
  "name": "Алгебра",
  "teacher_name": "Иванова С.П.",
  "teacher_phone": "+79990001122",
  "room": "304",
  "teacher2_name": null,
  "teacher2_phone": null,
  "room2": null,
  "whatsapp_url": "https://wa.me/79990001122",
  "whatsapp2_url": null
}
```

`POST /subjects`, `PUT /subjects/{id}`, `DELETE /subjects/{id}` — только админ.

### Каникулы

`GET /vacations` — все периоды каникул (сначала новые).

```json
{ "id": 2, "name": "Осенние", "start_date": "2026-10-26", "end_date": "2026-11-03" }
```

`POST /vacations`, `PUT /vacations/{id}`, `DELETE /vacations/{id}` — только админ.

### Дежурные

`GET /duty` — дежурные на все семь дней недели. Строки разбираются на имя и логин (`Иван И. (ivan)`); `linked` — логин совпал с существующим пользователем, `is_me` — это строка того, кто делает запрос, `is_today` — текущий день.

```json
{
  "day_of_week": 1,
  "name": "Понедельник",
  "text": "Иван И. (ivan)\nПётр П.",
  "entries": [
    { "name": "Иван И.", "login": "ivan", "linked": true, "is_me": true },
    { "name": "Пётр П.", "login": null, "linked": false, "is_me": false }
  ],
  "is_today": true
}
```

`PUT /duty/{day_of_week}` — `{"text": "Иван И. (ivan)\nПётр П."}` заменяет список дежурных на день (1–7, только админ). Пустой `text` очищает день, длина — до 2000 символов.

### Авторизация

`POST /auth/login` — `{"username": "root", "password": "..."}` → `{"access_token": "...", "token_type": "bearer"}`.

`POST /auth/logout` — выйти: удаляет cookie и отзывает выданные токены (старый `access_token` перестаёт работать). Для ботов не нужно — удалите ключ.

## Подгруппы

У пользователя может быть `subgroup` = 1, 2 или `null`. Ученик видит уроки и ДЗ своей подгруппы плюс общие (`subgroup = null`). Админ без подгруппы видит всё.

## Пример бота на Python

```python
import httpx

KEY = "lk_..."
BASE = "https://example.com/api/v1"
headers = {"Authorization": f"Bearer {KEY}"}

with httpx.Client(headers=headers, timeout=10) as client:
    summary = client.get(f"{BASE}/summary").raise_for_status().json()

for lesson in summary["lessons"]:
    print(lesson["lesson_number"], lesson["start_time"], lesson["subject"]["name"])
    for hw in lesson["homework"]:
        print("  ДЗ:", hw["title"], hw["status"])
```
