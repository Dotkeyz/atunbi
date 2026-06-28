# 1. The Base Image (Start with a tiny Linux machine with Python 3.11)
FROM python:3.11-slim

# 2. Environment Variables (Keep logs clean and direct)
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# 3. The Working Directory (Create the 'floor' of our container)
WORKDIR /app

# 4. The Dependencies (Copy the list and install them)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 5. The Code (Copy our Python file into the container)
COPY main.py .

# 6. The Port (Expose the internal port the app listens on)
EXPOSE 8000

# 7. The Ignition Key (Command to run when the container starts)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]