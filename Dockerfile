# --- CSS build stage (Tailwind v4 needs Node 20+) ---
FROM node:20-alpine AS css
WORKDIR /src
COPY package.json ./
RUN npm install --no-audit --no-fund
COPY web ./web
RUN npx tailwindcss -i web/styles.src.css -o web/static/styles.css --minify

# --- runtime stage ---
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
COPY mcp.json ./mcp.json
COPY --from=css /src/web/static/styles.css ./web/static/styles.css
COPY docker/entrypoint.sh /app/entrypoint.sh
COPY migrate_to_pg.py /app/migrate_to_pg.py

RUN chmod +x /app/entrypoint.sh \
 && mkdir -p /app/data /home/appuser \
 && chown -R 1000:1000 /app/data /home/appuser

EXPOSE 8080
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080"]
