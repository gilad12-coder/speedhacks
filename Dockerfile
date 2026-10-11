FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY househunt ./househunt
ENV DB_PATH=/data/househunt.db PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "uvicorn househunt.web.app:app --host 0.0.0.0 --port ${PORT}"]
