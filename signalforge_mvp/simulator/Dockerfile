# SignalForge traffic simulator
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY traffic_simulator.py .

# Default environment — override in docker-compose or at runtime
ENV API_URL=http://backend:8000
ENV TENANT_ID=demo-company
ENV PHASES=100
ENV INTERVAL=0.1

CMD ["python", "traffic_simulator.py"]
