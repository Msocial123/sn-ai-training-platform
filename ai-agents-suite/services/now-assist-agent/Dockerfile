# Build from the ai-agents-suite/ ROOT (not this folder), so it can pick up
# the shared library and dataset:
#   docker build -f services/now-assist-agent/Dockerfile -t now-assist-agent:latest .
FROM python:3.12-slim
WORKDIR /app
COPY services/now-assist-agent/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY services/now-assist-agent/app.py .
COPY shared /app/shared
COPY data /app/data
EXPOSE 8080
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
