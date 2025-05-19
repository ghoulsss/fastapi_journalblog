1. docker build . -t fastapi-back
2. docker run --name backend -e DB_NAME=journalblog -e DB_USER=postgres -e DB_PASS=postgres -e DB_PORT=5432 -e DB_HOST=localhost -p 8000:4000 -v ${PWD}:/app fastapi-back
---
http://127.0.0.1:8000/ back
http://127.0.0.1:8080/ adminer