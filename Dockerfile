# One image for every Python service: simulators, dispatcher, flows, consumers, API, dashboard.
FROM python:3.12.16-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/src

WORKDIR /app
# bcftools: slices public 1000 Genomes VCFs over HTTP (scripts/fetch_open_data.py).
RUN apt-get update && apt-get install -y --no-install-recommends bcftools \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .

CMD ["python", "-m", "omics.cli", "--help"]
