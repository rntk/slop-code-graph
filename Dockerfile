FROM python:3.12-slim

WORKDIR /app

# Install dependencies first (layer-cached separately from app code)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY graph.py .
COPY src/ src/

# Pre-download JS libraries so the container works offline
RUN python graph.py --help > /dev/null 2>&1 || true
RUN python - << 'EOF'
from src.renderer import get_js_bundle
get_js_bundle()
EOF

ENTRYPOINT ["python", "graph.py"]
