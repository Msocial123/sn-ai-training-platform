# Build from the ai-agents-suite/ ROOT (not this folder), so it can pick up
# the shared library and dataset:
#   docker build -f services/password-reset-agent/Dockerfile -t password-reset-agent:latest .
FROM python:3.12-slim
WORKDIR /app
COPY services/password-reset-agent/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY services/password-reset-agent/app.py .
COPY shared /app/shared
COPY data /app/data
EXPOSE 8080
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
