FROM jrottenberg/ffmpeg:6-ubuntu

# Install Python 3.12 and required system dependencies
RUN apt-get update && \
    apt-get install -y software-properties-common && \
    add-apt-repository ppa:deadsnakes/ppa && \
    apt-get update && \
    apt-get install -y \
        python3.12 \
        python3.12-venv \
        python3.12-dev \
        python3-pip \
        tesseract-ocr \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Set python3.12 as default python
RUN ln -s /usr/bin/python3.12 /usr/local/bin/python && \
    ln -s /usr/bin/python3.12 /usr/local/bin/python3 && \
    curl -sS https://bootstrap.pypa.io/get-pip.py | python3.12

WORKDIR /app

COPY worker/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared and worker code
COPY shared/ ./shared/
COPY worker/ ./worker/
COPY assets/ ./assets/

# Command to run RQ worker
CMD ["python", "-m", "rq.cli", "worker", "video_jobs", "--url", "$REDIS_URL"]
