# Dockerfile combinado: API + Worker + FFmpeg en un solo servicio
FROM python:3.12-slim

# Force Python to print logs immediately (no buffering)
ENV PYTHONUNBUFFERED=1

# Instalar FFmpeg, Tesseract y dependencias del sistema
RUN apt-get update && apt-get install -y \
    ffmpeg \
    tesseract-ocr \
    libpq-dev \
    gcc \
    supervisor \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Instalar dependencias Python (combinadas de api + worker)
COPY api/requirements.txt /tmp/api-requirements.txt
COPY worker/requirements.txt /tmp/worker-requirements.txt
RUN pip install --no-cache-dir -r /tmp/api-requirements.txt -r /tmp/worker-requirements.txt

# Copiar todo el código
COPY shared/ ./shared/
COPY api/ ./api/
COPY worker/ ./worker/
COPY seed.py ./seed.py
COPY assets/ ./assets/

# Configuración de supervisord para correr API y Worker juntos
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

EXPOSE 8000

# Seed the database on startup, then run supervisord
CMD python seed.py && supervisord -c /etc/supervisor/conf.d/supervisord.conf
