FROM python:3.12.15-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /opt/acs
COPY coordination/ ./coordination/
EXPOSE 10000
CMD ["python", "-m", "coordination.staging"]
