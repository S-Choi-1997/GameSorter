FROM python:3.11-slim
WORKDIR /app
RUN pip install flask gunicorn
COPY app.py .
ENV PORT=8080
EXPOSE 8080
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--timeout", "120", "app:app"]