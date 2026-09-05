# Build from the ai-agents-suite/ ROOT:
#   docker build -f services/incident-watcher/Dockerfile -t incident-watcher:latest .
FROM python:3.12-slim
WORKDIR /app
COPY services/incident-watcher/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY services/incident-watcher/app.py .
COPY shared /app/shared
COPY data /app/data
EXPOSE 8080
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
