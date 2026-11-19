FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.8 /uv /uvx /bin/

# Keep the Python environment available when the checkout is mounted at /app.
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=0 \
    UV_LINK_MODE=copy \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    XDG_CACHE_HOME=/tmp/streamvault-cache \
    IPYTHONDIR=/tmp/streamvault-ipython \
    JUPYTER_CONFIG_DIR=/tmp/streamvault-jupyter/config \
    JUPYTER_RUNTIME_DIR=/tmp/streamvault-jupyter/runtime

WORKDIR /app

COPY pyproject.toml README.md uv.lock .python-version ./

# Install JupyterLab and the other locked dependencies before copying project files.
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-install-project

COPY src ./src
COPY config.toml id_list.csv ./
COPY notebooks ./notebooks
COPY docs ./docs

# An editable install lets the package find config.toml and use the mounted checkout.
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked

EXPOSE 8888
CMD ["jupyter", "lab", "--ip=0.0.0.0", "--port=8888", "--no-browser", "--allow-root"]
