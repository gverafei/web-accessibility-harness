FROM python:3.13.16-alpine3.24

WORKDIR /app

# Connector/Pillow wheels need no compiler or MySQL CLI at runtime.
RUN apk upgrade --no-cache
COPY requirements.txt /tmp/requirements.txt
RUN python -m pip install --no-cache-dir --upgrade pip==26.2.1 && \
    python -m pip install --no-cache-dir --only-binary=:all: -r /tmp/requirements.txt && \
    python -m pip uninstall -y pip && \
    rm /tmp/requirements.txt

COPY app/ /app/
RUN pybabel compile -d /app/translations

EXPOSE 5000
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--threads", "4", "--timeout", "60", "main:app"]
