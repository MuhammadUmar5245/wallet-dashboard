FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5000
# init_db.py waits for Postgres, creates tables + sample data on first start only, then gunicorn starts
CMD ["sh", "-c", "python init_db.py && exec gunicorn -b 0.0.0.0:5000 -w 2 app:app"]
