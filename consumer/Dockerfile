FROM python:3.11-slim
WORKDIR /app
RUN pip install aiokafka
COPY main.py .
CMD ["python", "-u", "main.py"]
