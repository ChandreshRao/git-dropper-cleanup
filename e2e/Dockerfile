# End-to-end test image: infected git history -> git-dropper-cleanup --rewrite -> clean --check
FROM python:3.12-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src/
COPY sign_history ./sign_history/
COPY e2e/run.sh ./e2e/run.sh

RUN chmod +x e2e/run.sh \
    && uv sync --extra dev

CMD ["bash", "e2e/run.sh"]
