# Built from the repository root (see compose.yaml) so the image can carry the shipped
# Cerbos policies and the Cerbos CLI, which validates browser edits before Cerbos sees them.
FROM ghcr.io/cerbos/cerbos:0.57.0@sha256:e5e3b150b3cb0090975605254f255164567d67e233634199fb20972e3eaff300 AS cerbos

FROM python:3.12-slim AS runtime
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir --require-hashes -r requirements.txt
COPY --from=cerbos /cerbos /usr/local/bin/cerbos
# /policies is where the live-policy volume mounts; owned by the API so it can write.
RUN useradd --system --no-create-home --uid 10001 app && mkdir /policies && chown app:app /policies
COPY --chown=app:app backend/alembic.ini ./
COPY --chown=app:app backend/migrations ./migrations
COPY --chown=app:app backend/app ./app
# The baseline for "reset policies" and for diffs against what shipped.
COPY --chown=app:app cerbos/policies ./shipped-policies
USER app
CMD ["sh", "-c", "alembic upgrade head && python -m app.seed && python -m app.policy_store sync && uvicorn app.main:app --host 0.0.0.0 --port 8000"]

# Test image: runtime plus test dependencies, tests and scripts. Used by `demo.py test`
# and CI through the compose "test" profile.
FROM runtime AS test
USER root
COPY backend/requirements-dev.txt .
RUN pip install --no-cache-dir --require-hashes -r requirements-dev.txt
COPY --chown=app:app backend/tests ./tests
COPY --chown=app:app backend/pyproject.toml ./
COPY --chown=app:app scripts/test.py scripts/smoke.py ./scripts/
USER app
CMD ["python", "scripts/test.py"]
