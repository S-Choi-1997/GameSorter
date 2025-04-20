# Python 3.11 경량 이미지 사용
FROM python:3.11-slim AS base

# 필수 시스템 패키지 설치 (예: GCS, OpenAI 클라이언트 등 일부 빌드 종속성)
RUN apt-get update && apt-get install -y \
    gcc \
    libffi-dev \
    libpq-dev \
    curl \
    git \
 && rm -rf /var/lib/apt/lists/*

# 작업 디렉토리 설정
WORKDIR /app

# Python 패키지 종속성 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 앱 코드 복사
COPY . .

# 환경 변수
ENV PORT=8080

# 실행
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 app:app
