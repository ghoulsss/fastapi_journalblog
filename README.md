# FastAPI JournalBlog

Асинхронный REST API блога: пользователи, JWT, статьи, категории и теги.
Python 3.12+, FastAPI, SQLAlchemy 2, PostgreSQL, Alembic и Redis.

## Быстрый запуск без Docker

Нужен uv. Выполните из корня проекта (Python 3.12 uv установит при необходимости):

```bash
uv sync --locked --python 3.12
cp -n .env.example .env
uv run --locked python scripts/generate_jwt_keys.py
export DATABASE_URL=sqlite+aiosqlite:///./journalblog.db
uv run --locked alembic upgrade head
uv run --locked uvicorn main:app --host 127.0.0.1 --port 8000
```

Откройте **http://127.0.0.1:8000/docs**. Остановка — `Ctrl+C`.
Копирование `.env` и генерация ключей нужны только при первом запуске;
существующие ключи генератор не перезаписывает. Для повторного запуска достаточно
двух команд: `export DATABASE_URL=sqlite+aiosqlite:///./journalblog.db` и команды
`uv run --locked uvicorn ...` выше. Вместо `export` можно записать `DATABASE_URL`
в `.env`.

Redis для основного API не обязателен: без него `/health/redis` возвращает 503.
Для внешнего PostgreSQL не задавайте `DATABASE_URL` и заполните `POSTGRES_*`
в `.env`. Перед переходом с SQLite на Docker выполните `unset DATABASE_URL`
и удалите эту переменную из `.env`, если добавляли её туда.

Если старое `.venv` перенесено с другой ОС, перед командами выше выполните
`export UV_PROJECT_ENVIRONMENT=.venv-check`: uv использует отдельное окружение
внутри проекта. Эта переменная должна оставаться заданной и при повторном запуске.

## Docker Compose

Подготовьте `.env` и ключи командами выше. В `.env` задайте свой
`POSTGRES_PASSWORD`; `DATABASE_URL` для этого режима должен быть удалён.
Затем на macOS/Linux:

```bash
LOCAL_UID=$(id -u) LOCAL_GID=$(id -g) docker compose up --build
```

UID/GID позволяют контейнеру читать приватный ключ с правами 0600, не открывая
его другим пользователям. Эти значения можно сохранить как `LOCAL_UID` и
`LOCAL_GID` в `.env`. По умолчанию используются 1000:1000.

API: http://127.0.0.1:8000/docs. Compose ожидает готовности PostgreSQL и Redis
и выполняет `alembic upgrade head` перед запуском API. Ключи монтируются только
для чтения; локальные окружения, `.env` и ключи не включаются в Docker-образ.
Порты базы и Redis не публикуются наружу. Для Adminer:

```bash
docker compose --profile tools up -d adminer
```

Adminer: http://127.0.0.1:8080, сервер базы — `db`.
`nginx/nginx.conf` — отдельный пример проксирования с хоста на порт 8000;
он не входит в Compose и требует настройки домена/TLS перед публикацией.

## Работа с API

1. `POST /api/v1/users` — регистрация JSON-телом:
   `{"username":"alice","email":"alice@example.com","password":"password123"}`.
2. `POST /api/v1/jwt/login` — форма `username=alice&password=password123`.
3. Передавайте `Authorization: Bearer <access_token>` для изменения данных.
   В Swagger используйте кнопку **Authorize**.
4. `POST /api/v1/jwt/refresh` принимает **refresh token** в том же заголовке
   и возвращает новый access token. Refresh token действует до своего истечения;
   ротация и отдельный logout пока не реализованы.

| Ресурс | Доступные операции |
| --- | --- |
| `/api/v1/users` | POST регистрация, GET список |
| `/api/v1/users/{id}` | GET, DELETE собственного аккаунта без статей |
| `/api/v1/users/by-username/{username}` | GET поиск по имени |
| `/api/v1/users/{id}/articles` | GET пользователь со статьями |
| `/api/v1/articles` | GET список, POST создание |
| `/api/v1/articles/{id}` | GET, PATCH и DELETE автором |
| `/api/v1/categories`, `/api/v1/tags` | GET список, POST создание |
| `/api/v1/categories/{id}`, `/api/v1/tags/{id}` | GET, PATCH, DELETE |
| `/api/v1/jwt/users/me` | GET текущий активный пользователь |
| `/health/db`, `/health/redis` | GET доступность сервиса, 503 при ошибке |

Создание статьи (категория и теги должны существовать):

```json
{
  "title": "Первый пост",
  "content": "Текст статьи",
  "category_id": 1,
  "tag_ids": [1, 2],
  "is_published": "published"
}
```

Создание и переименование категорий/тегов принимает `{"name":"Python"}`.
Успешное создание возвращает 201 и объект с ID. PATCH принимает изменяемые поля;
`tag_ids: []` очищает теги. Несуществующие ссылки возвращают 400/404,
дубликаты имён/email и удаление используемой категории — 409.
Списки поддерживают `offset >= 0`, `1 <= limit <= 100`.

Чтение пользователей и статей публичное, включая email и статьи со статусом
`nonpublished`: статус публикации пока является метаданными, а не настройкой
приватности. Категории и теги общие: менять их может любой активный пользователь.
`is_author` сохранён для совместимости данных и не является ролью администратора.
Удаление тега убирает его связи со статьями; удаление категории со статьями запрещено.

## Настройки и совместимость

Настройки читаются из `.env` в корне проекта и переменных окружения. Последние
имеют приоритет. `DATABASE_URL` имеет приоритет над отдельными `POSTGRES_*`.
`CORS_ORIGINS` — JSON-список разрешённых origin. Вложенные JWT-настройки используют
`__`, например `AUTH_JWT__ACCESS_TOKEN_EXPIRED_MINUTES=30`.

Пароль: от 8 символов до 72 байт UTF-8; хранится bcrypt-хеш. JWT подписывается
RS256; `sub` содержит ID пользователя. Старые токены с username в `sub` требуют
повторного входа. Срок access token по умолчанию — 60 минут, refresh — 30 дней.
Секретные ключи нельзя коммитить. Генератор откажется перезаписывать существующую пару.

Изменения относительно старого API: запросы создания используют JSON вместо
query-параметров; ответы создания — типизированные объекты; изменения требуют
авторизации; дублирующийся маршрут поиска пользователя перенесён на
`/users/by-username/{username}`. Публичный `/db-recreate` удалён.

Старые миграции сохранены. Новая ревизия создаёт таблицы, соответствующие моделям.
Если в старых таблицах есть данные, автоматическое обновление остановится:
подробности в [src/migrations/README](src/migrations/README). Не используйте
`drop_all` или `docker compose down -v` для обновления существующей базы.

## Проверки

```bash
uv run pytest --basetemp=.cache/pytest -q
uv run ruff check .
uv run ruff format --check config.py main.py src tests scripts
```

Тесты используют отдельные SQLite-базы, временные RSA-ключи и имитацию Redis;
рабочая база не затрагивается. Проверяются регистрация, JWT/refresh, права,
CRUD и связи, валидация, CORS, health checks, миграции и сохранность старых данных.
Живые PostgreSQL/Redis и сборку образа дополнительно проверяйте через Compose.

Зависимости управляются только через uv. Единственный lock-файл — `uv.lock`.
Добавление пакета: `uv add <пакет>`, инструмента разработки: `uv add --dev <пакет>`.
После изменения зависимостей коммитьте `pyproject.toml` и `uv.lock` вместе.

Структура проекта описана в [structure.md](structure.md).
