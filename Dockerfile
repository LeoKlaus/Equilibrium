FROM python:3.14-slim

# Unbuffered stdout/stderr - without this, output isn't a real TTY inside
# a container and Python fully block-buffers it, which can silently lose
# the last chunk of output (including tracebacks) if the process exits
# abruptly before the buffer flushes.
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# No multi-stage build here: web/ is a pre-built Flutter bundle already
# committed to the repo (no frontend build step), and requirements.txt's
# packages all ship prebuilt wheels for the platforms this targets
# (notably pyrf24, which has manylinux/musllinux wheels for aarch64 and
# armv7l), so no C/C++ build toolchain is needed in the image.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENTRYPOINT ["python", "main.py"]
