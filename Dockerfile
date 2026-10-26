FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8010

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY capabilities_gateway capabilities_gateway
COPY skills skills

EXPOSE 8010
CMD ["python", "-m", "capabilities_gateway"]
