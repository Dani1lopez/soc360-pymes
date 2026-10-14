FROM python:3.12-slim
WORKDIR /app
COPY fake_services.py /app/fake_services.py
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
CMD ["python", "/app/fake_services.py"]
