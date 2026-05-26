FROM python:3.10-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip && \
    pip install \
    mistralai==1.9.7 \
    fastapi \
    uvicorn \
    pydantic \
    fpdf2

COPY main.py .

CMD ["python", "main.py"]
