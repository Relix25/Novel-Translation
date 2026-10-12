FROM node:22-bookworm-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM node:22-bookworm-slim AS runtime
ARG CODEX_VERSION=0.162.0-alpha.17.2
RUN apt-get update && apt-get install -y --no-install-recommends python3 ca-certificates git \
    && rm -rf /var/lib/apt/lists/* \
    && npm install -g @openai/codex@${CODEX_VERSION} \
    && mkdir -p /home/node/.codex /data/library /imports \
    && chown -R node:node /home/node/.codex /data /imports
WORKDIR /opt/novel
COPY *.py ./
COPY prompts/ ./prompts/
COPY --from=frontend /build/dist ./frontend/dist/
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
USER node
EXPOSE 8788
CMD ["python3", "app.py", "--root", "/data/library", "--bind", "0.0.0.0", "--port", "8788", "--public-origin", "http://127.0.0.1:8791", "--no-browser"]
