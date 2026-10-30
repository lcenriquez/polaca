FROM python:3.12-slim

WORKDIR /app

COPY auditor/requirements.txt auditor/requirements.txt
RUN pip install --no-cache-dir -r auditor/requirements.txt

COPY auditor/ auditor/

EXPOSE 8080

CMD ["uvicorn", "web:app", "--app-dir", "auditor", "--host", "0.0.0.0", "--port", "8080"]
