# Build from the ai-agents-suite/ ROOT:
#   docker build -f services/infra-monitor/Dockerfile -t infra-monitor:latest .
FROM python:3.12-slim
WORKDIR /app
COPY services/infra-monitor/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY services/infra-monitor/app.py .
EXPOSE 8080
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
