# Use Python 3.11 slim image for a smaller footprint
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create directory for config and database
RUN mkdir -p /config
VOLUME /config

# Set environment variable to use mounted config
ENV SHOWSWEEP_CONFIG=/config/config.ini

# Command to run
CMD ["python", "main.py"]