# SignalForge traffic simulator
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY traffic_simulator.py .

# Default environment — override in docker-compose or at runtime. These match
# the variables traffic_simulator.py actually reads; the defaults target the
# `backend` service on the compose network.
ENV API_URL=http://backend:8000/ingest
ENV API_KEY=sf-api-key-demo
ENV TENANT_ID=demo-company
ENV EVENT_INTERVAL=0.25
ENV NORMAL_EVENTS=50
ENV TOTAL_EVENTS=0

CMD ["python", "traffic_simulator.py"]
