# Hugging Face Spaces, Docker SDK. Built for the free CPU runtime: 16GB RAM, 2 vCPU,
# no GPU, and a filesystem that resets whenever the Space rebuilds.
FROM python:3.9-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# poppler-utils is pdf2image's system dependency: without it every upload fails at the
# first step. curl fetches the model checkpoint at boot.
RUN apt-get update && apt-get install -y --no-install-recommends \
        poppler-utils curl \
    && rm -rf /var/lib/apt/lists/*

# Spaces run the container as uid 1000.
RUN useradd -m -u 1000 user

WORKDIR /app

# CPU-only torch, installed before everything else. The default PyPI wheel bundles ~2.5GB
# of CUDA libraries that a CPU Space can never load; these are ~200MB and identical for
# our purposes. Pinned to the same versions requirements.txt asks for, so the next pip
# install sees them as satisfied and leaves them alone.
RUN pip install --index-url https://download.pytorch.org/whl/cpu \
        torch==2.7.1 torchvision==0.22.1

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY --chown=user:user soulfont/ /app/
COPY --chown=user:user docker/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# /data is where Spaces mount persistent storage if it is enabled. Created here so the
# same paths work on the free tier, where it is just another directory in the container
# and its contents are lost on rebuild.
RUN mkdir -p /data && chown user:user /data /app

ENV DJANGO_DEBUG=0 \
    DJANGO_ALLOWED_HOSTS=".hf.space,localhost,127.0.0.1" \
    DJANGO_CSRF_TRUSTED_ORIGINS="https://*.hf.space" \
    DJANGO_BEHIND_PROXY=1 \
    SOULFONT_DATA_DIR=/data \
    SOUL_FONT_DEVICE=cpu \
    PORT=7860

USER user
EXPOSE 7860
CMD ["/app/entrypoint.sh"]
