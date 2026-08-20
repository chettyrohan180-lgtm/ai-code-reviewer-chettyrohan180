# Multi-stage production Dockerfile for Autonomous AI Code Reviewer
# ====================================================================

FROM python:3.12-slim AS builder

WORKDIR /app

# Install system build dependencies for C-extensions (tree-sitter, cryptography)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt


# ── Final Runtime Stage ──────────────────────────────────────────────
FROM python:3.12-slim AS runner

WORKDIR /app

# Create a non-root user for security
RUN groupadd -r appgroup && useradd -r -g appgroup -u 1001 appuser

# Copy installed Python packages from builder stage
COPY --from=builder /root/.local /home/appuser/.local
ENV PATH=/home/appuser/.local/bin:$PATH

# Copy application source code
COPY --chown=appuser:appgroup ai_code_reviewer/ /app/ai_code_reviewer/

# Create secrets mount point
RUN mkdir -p /app/secrets && chown -R appuser:appgroup /app/secrets

USER appuser

EXPOSE 8000

ENV PORT=8000 \
    APP_ENV=production \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')" || exit 1

# Entrypoint
CMD ["uvicorn", "ai_code_reviewer.main:app", "--host", "0.0.0.0", "--port", "8000"]
