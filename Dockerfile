FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir \
    fastapi==0.115.* \
    "uvicorn[standard]==0.32.*" \
    streamlit==1.40.* \
    pandas==2.2.* \
    requests==2.32.* \
    pyyaml==6.0.*
COPY . .
ENV PYTHONUNBUFFERED=1
