FROM python:3.11-slim

# 작업 디렉토리 설정
WORKDIR /app

# requirements.txt 복사 및 의존성 설치
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt


RUN playwright install --with-deps
# app.py 복사
COPY app.py ./

# 환경변수 및 포트 설정
ENV PORT=8080
EXPOSE 8080

# 서버 실행 (gunicorn)
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--timeout", "120", "app:app"]
