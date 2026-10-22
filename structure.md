# Структура проекта

```text
fastapi_journalblog/
├── main.py                       # FastAPI, lifespan, CORS, подключение маршрутов
├── config.py                     # Настройки из окружения и .env
├── pyproject.toml                # Зависимости и инструменты разработки
├── uv.lock                       # Lock-файл uv и Docker
├── Dockerfile
├── compose.yml                   # API, PostgreSQL, Redis, необязательный Adminer
├── alembic.ini
├── .env.example
├── scripts/generate_jwt_keys.py   # Генерация локальных ключей RS256
├── certs/                        # Локальные ключи, исключены из Git и образа
├── src/
│   ├── api_v1/
│   │   ├── routers/              # Пользователи, статьи, категории, теги, health
│   │   └── schemas/              # Pydantic-схемы запросов и ответов
│   ├── auth/utils.py             # Подпись/проверка JWT и bcrypt
│   ├── demo_auth/                # Маршруты JWT, проверка пользователя, токены
│   ├── db/                       # ORM-модели, связи, сессии и транзакции
│   └── migrations/               # Alembic и последовательные ревизии
├── tests/                        # API и миграции на изолированной SQLite
└── nginx/nginx.conf              # Пример reverse proxy вне Compose
```

Папки `.venv*`, `.tools` и `.cache` — локальные окружения и результаты проверок;
они не входят в Git или Docker-образ.
