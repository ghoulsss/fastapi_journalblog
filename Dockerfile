FROM python:3.12-slim

RUN pip install poetry
RUN poetry config virtualenvs.create false

ENV PYTHONUNBUFFERED=1
WORKDIR /fastapi_journalblog
COPY pyproject.toml poetry.lock ./
RUN poetry install --no-interaction --no-ansi --no-root
COPY . .
CMD ["python", "main.py"]