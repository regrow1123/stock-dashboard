FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=Asia/Seoul

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates nodejs npm tzdata \
 && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone \
 && rm -rf /var/lib/apt/lists/*

RUN npm install -g @anthropic-ai/claude-code

WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e .

COPY app ./app
COPY web ./web
COPY seed ./seed

RUN mkdir -p /app/data

EXPOSE 8080
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080"]
