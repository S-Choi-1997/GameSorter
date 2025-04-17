# Python 3.11 경량 이미지 사용
FROM python:3.11-slim

# 작업 디렉토리 설정
WORKDIR /app

# Python 종속성 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 애플리케이션 코드 복사
COPY . .

# 환경 변수 설정
ENV PORT=8080

# 실행 명령
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 app:app