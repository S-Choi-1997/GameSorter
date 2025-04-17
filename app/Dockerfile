# Python 3.11 기반 이미지 사용
FROM python:3.11-slim

# 작업 디렉토리 설정
WORKDIR /app

# 종속성 파일 복사 및 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 애플리케이션 파일 복사
COPY . .

# Flask 앱 실행 환경 변수 설정
ENV FLASK_APP=app.py
ENV FLASK_ENV=production

# 포트 8080에서 실행 (Cloud Run 기본 포트)
EXPOSE 8080

# 앱 실행 명령
CMD ["flask", "run", "--host=0.0.0.0", "--port=8080"]