FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY server.py /app/server.py

EXPOSE 9019/tcp

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import socket; s=socket.create_connection(('127.0.0.1', 9019), 2); s.close()"

CMD ["python", "/app/server.py"]
