FROM python:3.12-slim

WORKDIR /app

# rawpy wheels include bundled libraw, no system package needed
COPY requirements.txt .
RUN pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/ && \
    pip config set global.trusted-host mirrors.aliyun.com && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p album/relic album/animal album/plant \
    thumbs/relic thumbs/animal thumbs/plant \
    uploads

EXPOSE 8000

CMD ["python", "main.py"]
