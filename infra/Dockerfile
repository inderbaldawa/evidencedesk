# Cloud Build is the build host; --platform in cloudbuild.yaml forces linux/amd64.
FROM node:22-bookworm-slim AS frontend
WORKDIR /build
COPY app/frontend/package.json app/frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY app/frontend/index.html app/frontend/tsconfig.json app/frontend/vite.config.ts ./
COPY app/frontend/src ./src
RUN npm run build

FROM python:3.12-slim-bookworm AS wheels
WORKDIR /build
COPY app/requirements.lock ./requirements.lock
RUN python -m pip wheel --no-cache-dir --wheel-dir=/wheels -r requirements.lock

FROM python:3.12-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080 EVIDENCEDESK_DATA_DIR=/tmp/evidencedesk
WORKDIR /srv
COPY --from=wheels /wheels /wheels
COPY app/requirements.lock /srv/requirements.lock
RUN python -m pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.lock \
    && rm -rf /wheels \
    && useradd --uid 10001 --create-home evidencedesk
COPY app/backend /srv/app/backend
COPY data/demo-packs /srv/data/demo-packs
COPY --from=frontend /build/dist /srv/app/frontend/dist
USER 10001
EXPOSE 8080
CMD ["sh", "-c", "exec python -m uvicorn app.backend.main:app --host 0.0.0.0 --port ${PORT:-8080} --proxy-headers --forwarded-allow-ips='*'"]
