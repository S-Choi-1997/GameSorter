FROM python:3.11
WORKDIR /app

RUN apt update && apt install -y \
    libgl1 \
    libxkbcommon0

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
CMD ["sleep", "infinity"]
