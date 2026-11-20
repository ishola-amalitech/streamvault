FROM python:3.14-slim AS pipeline

COPY --from=ghcr.io/astral-sh/uv:0.13.8 /uv /bin/uv

# Keep the Python environment available when the checkout is mounted at /app.
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=0 \
    UV_LINK_MODE=copy \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    XDG_CACHE_HOME=/tmp/streamvault-cache

WORKDIR /app

# Cache the locked dependencies separately so source edits do not reinstall them.
COPY pyproject.toml README.md uv.lock .python-version ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev --no-install-project

COPY src ./src
COPY app.py config.toml id_list.csv ./
COPY .streamlit/config.toml ./.streamlit/config.toml

# An editable install lets the package find config.toml in the mounted checkout.
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev

EXPOSE 8501
CMD ["streamvault"]

# Add Jupyter only when building the notebook image.
FROM pipeline AS notebooks

ENV IPYTHONDIR=/tmp/streamvault-ipython \
    JUPYTER_CONFIG_DIR=/tmp/streamvault-jupyter/config \
    JUPYTER_RUNTIME_DIR=/tmp/streamvault-jupyter/runtime

RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked
COPY notebooks ./notebooks
COPY docs ./docs
COPY lab_brief.md ./

EXPOSE 8888
CMD ["jupyter", "lab", "--ip=0.0.0.0", "--port=8888", "--no-browser", "--allow-root"]

# A plain docker build produces the pipeline and app image.
FROM pipeline AS runtime
