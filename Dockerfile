FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DENO_DIR=/opt/deno-cache
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl git unzip ffmpeg \
    && curl -fsSL https://deno.land/install.sh | sh \
    && install -m 0755 /root/.deno/bin/deno /usr/local/bin/deno \
    && git clone --depth 1 --branch 1.3.1 https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git /opt/bgutil-ytdlp-pot-provider \
    && cd /opt/bgutil-ytdlp-pot-provider/server \
    && deno install --allow-scripts=npm:canvas --frozen \
    && apt-get purge -y --auto-remove curl git unzip \
    && rm -rf /var/lib/apt/lists/* /root/.deno
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
RUN useradd --create-home --uid 10001 appuser && mkdir -p /tmp/subdown /opt/deno-cache && chown -R appuser:appuser /app /tmp/subdown /opt/bgutil-ytdlp-pot-provider /opt/deno-cache
USER appuser
EXPOSE 8000
CMD ["sh","-c","cd /opt/bgutil-ytdlp-pot-provider/server/node_modules && /usr/local/bin/deno run --allow-env --allow-net --allow-ffi=. --allow-read=. ../src/main.ts & exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
