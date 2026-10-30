FROM python:3.12-slim

WORKDIR /app

COPY auditor/requirements.txt auditor/requirements.txt
RUN pip install --no-cache-dir -r auditor/requirements.txt

COPY auditor/ auditor/
COPY datos/semilla/ datos/semilla/

ENV DATA_DIR=/tmp/polaca

EXPOSE 8080

CMD ["sh", "-c", "uvicorn web:app --app-dir auditor --host 0.0.0.0 --port ${PORT:-8080}"]
