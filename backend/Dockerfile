FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv/prguard

COPY pyproject.toml ./
COPY app ./app
RUN pip install .

# The API process needs a writable data directory and, when using Docker-outside-
# of-Docker, access to the host daemon socket (documented security trade-off).
RUN useradd --create-home --uid 10001 prguard \
    && mkdir -p /data \
    && chown -R prguard:prguard /data
USER prguard

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
