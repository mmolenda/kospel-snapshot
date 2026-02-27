FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY kospel.py /app/kospel.py
COPY config /app/config
RUN cp /app/config/settings.example.toml /app/config/settings.toml

CMD ["python", "-u", "/app/kospel.py", "-v"]
