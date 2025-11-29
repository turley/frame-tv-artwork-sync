# Use minimal Python alpine image for smaller size
FROM python:3.11-alpine

# Set working directory
WORKDIR /app

# Install git (needed to install from GitHub) and cleanup
RUN apk add --no-cache git

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy sync script
COPY sync_artwork.py .

# Create directories for artwork and tokens
RUN mkdir -p /artwork /tokens

# Make script executable
RUN chmod +x sync_artwork.py

# Run the sync script
CMD ["python", "-u", "sync_artwork.py"]
