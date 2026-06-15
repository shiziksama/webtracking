FROM node:22-alpine AS frontend-build

WORKDIR /app

COPY frontend/package*.json ./
RUN npm install

COPY frontend/ ./
RUN npm run build


FROM nginx:1.27-alpine AS frontend

COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=frontend-build /app/dist /usr/share/nginx/html

EXPOSE 80


FROM python:3.11-slim AS backend

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install --no-install-recommends -y libglib2.0-0 libgl1 \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
