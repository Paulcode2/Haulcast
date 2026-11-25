# Backend API container (Render/Railway/Fly/Heroku Docker or any OCI host).
# Frontend deploys separately as a static site (see README + docs/testing/phase-08-production-verification.md).
FROM python:3.14-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000
WORKDIR /app
COPY backend/requirements.lock.txt ./backend/requirements.lock.txt
RUN pip install --no-cache-dir -r backend/requirements.lock.txt
COPY backend/ ./backend/
WORKDIR /app/backend
RUN python manage.py collectstatic --noinput
EXPOSE 8000
CMD ["sh", "-c", "gunicorn config.wsgi --bind 0.0.0.0:$PORT --workers 3 --timeout 60 --access-logfile - --error-logfile -"]
