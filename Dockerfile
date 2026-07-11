FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN pip install --no-cache-dir piper-tts==1.4.2 \
    && mkdir -p /app/voices \
    && python -m piper.download_voices \
        --data-dir /app/voices \
        pt_BR-faber-medium

COPY server.py /app/server.py

EXPOSE 9019/tcp

HEALTHCHECK --interval=30s --timeout=5s --start-period=45s --retries=3 \
    CMD python -c "import socket; s=socket.create_connection(('127.0.0.1', 9019), 2); s.close()"

CMD ["python", "/app/server.py"]
