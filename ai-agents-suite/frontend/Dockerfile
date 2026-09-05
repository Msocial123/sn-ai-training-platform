# Build from the ai-agents-suite/frontend/ folder:
#   docker build -t ai-agents-frontend:latest .
FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY index.html style.css app.js /usr/share/nginx/html/
EXPOSE 8080
