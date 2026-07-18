# Stage 1: Build frontend
FROM node:22-alpine AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ .
ENV NEXT_PUBLIC_API_URL=""
RUN npm run build

# Stage 2: Backend
FROM python:3.11-slim AS backend
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ .

# Stage 3: Nginx + everything
FROM python:3.11-slim
RUN apt-get update && apt-get install -y nginx && rm -rf /var/lib/apt/lists/*

# Backend
WORKDIR /app
COPY --from=backend /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=backend /usr/local/bin /usr/local/bin
COPY --from=backend /app /app

# Frontend (Next.js static export)
COPY --from=frontend-builder /app/frontend/out /usr/share/nginx/html

# Nginx config — replace default entirely
RUN rm -f /etc/nginx/sites-enabled/default && echo ' \
events { worker_connections 1024; } \
http { \
    include /etc/nginx/mime.types; \
    default_type application/octet-stream; \
    sendfile on; \
    keepalive_timeout 65; \
    server { \
        listen 80; \
        location /api/ { \
            proxy_pass http://127.0.0.1:8000; \
            proxy_http_version 1.1; \
            proxy_set_header Host $host; \
            proxy_set_header Connection ""; \
            proxy_buffering off; \
            proxy_read_timeout 600s; \
        } \
        location /mcp/ { \
            proxy_pass http://127.0.0.1:8000; \
            proxy_http_version 1.1; \
            proxy_set_header Host $host; \
            proxy_set_header Connection ""; \
            proxy_buffering off; \
        } \
        location /auth/ { proxy_pass http://127.0.0.1:8000; proxy_set_header Host $host; } \
        location /health { proxy_pass http://127.0.0.1:8000; proxy_set_header Host $host; } \
        location / { root /usr/share/nginx/html; try_files $uri $uri/ /index.html; } \
    } \
}' > /etc/nginx/nginx.conf

# Startup script
RUN echo '#!/bin/sh\nuvicorn main:app --host 0.0.0.0 --port 8000 &\nnginx -g "daemon off;"' > /start.sh && chmod +x /start.sh

EXPOSE 80
CMD ["/start.sh"]
