# syntax=docker/dockerfile:1

# Stage 1: build the React app into web/dist.
FROM node:20-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# Stage 2: slim Python image with the API, worker and the built UI.
FROM python:3.12-slim AS app

# WITH_RERANKER=1 installs sentence-transformers (CPU torch) and pre-downloads the cross-encoder so
# modes M4/M4S work. Build with --build-arg WITH_RERANKER=0 for a lean image: the API then falls
# back to M2S.
ARG WITH_RERANKER=1
ARG RERANKER_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/opt/hf

# api/main.py looks for the UI at <repo>/web/dist relative to the package source, so the package
# is installed editable from /app and the build lands at /app/web/dist.
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ src/
RUN pip install -e . \
 && if [ "$WITH_RERANKER" = "1" ]; then \
      pip install --extra-index-url https://download.pytorch.org/whl/cpu torch \
      && pip install -e ".[reranker]" \
      && python -c "from sentence_transformers import CrossEncoder; CrossEncoder('${RERANKER_MODEL}')"; \
    fi

COPY config.env config.prod.env ./
COPY eval/books/ eval/books/
COPY --from=web /web/dist web/dist

# Non-root user; /data (SQLite files, uploaded books, LLM cache) is a mounted volume.
RUN useradd --uid 1000 --create-home sailor \
 && mkdir -p /data /app/books /opt/hf \
 && chown -R sailor /data /app/books /opt/hf
USER sailor

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request as u; u.urlopen('http://localhost:8000/api/health')"

CMD ["uvicorn", "storyquest.api.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
