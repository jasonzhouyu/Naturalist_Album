FROM python:3.12-slim

WORKDIR /app

# Install libraw for rawpy
RUN apt-get update && apt-get install -y --no-install-recommends \
    libraw-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p album/relic album/animal album/plant \
    thumbs/relic thumbs/animal thumbs/plant \
    uploads

EXPOSE 8000

CMD ["python", "main.py"]
