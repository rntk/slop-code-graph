FROM python:3.12-slim

# Create a non-root user with a stable UID/GID (1000) so volume-mounted
# output files are owned by a typical host user rather than root.
RUN groupadd --gid 1000 appuser \
 && useradd --uid 1000 --gid 1000 --create-home appuser

WORKDIR /app

# Install dependencies as root (writes to system site-packages)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source and hand ownership to appuser
COPY graph.py .
COPY src/ src/
RUN chown -R appuser:appuser /app

# The renderer is fully self-contained (no external JS libraries to fetch),
# so there is nothing to pre-download — just drop to the non-root user.
USER appuser

ENTRYPOINT ["python", "graph.py"]
