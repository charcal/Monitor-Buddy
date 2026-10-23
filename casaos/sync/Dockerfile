FROM python:3.12-alpine
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 SITE_DIR=/site
WORKDIR /app
COPY sync.py .
VOLUME /site
CMD ["python", "-I", "sync.py"]
