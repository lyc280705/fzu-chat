FROM node:24-slim AS frontend-builder

WORKDIR /frontend

COPY frontend/package*.json ./
RUN npm install
COPY frontend ./
RUN npm run build

FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt ./
COPY app ./app
COPY --from=frontend-builder /frontend/dist ./frontend/dist

RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

CMD ["uvicorn", "app.server:app", "--host", "0.0.0.0", "--port", "8000"]
