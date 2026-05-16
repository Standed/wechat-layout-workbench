FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir pillow

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV HOST=0.0.0.0

EXPOSE 8765

CMD ["python", "web/server.py", "8765"]
