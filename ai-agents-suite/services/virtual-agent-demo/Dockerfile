# Build from the ai-agents-suite/ ROOT (not this folder), so it can pick up
# the shared library and dataset:
#   docker build -f services/virtual-agent-demo/Dockerfile -t virtual-agent-demo:latest .
FROM python:3.12-slim
WORKDIR /app
COPY services/virtual-agent-demo/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY services/virtual-agent-demo/app.py .
COPY shared /app/shared
COPY data /app/data
EXPOSE 8080
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
