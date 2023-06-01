# We will use the official Python 3.10 image from Docker Hub
FROM python:3.10-slim-buster

# Set a directory for our application
WORKDIR /app

# Install poetry for package management
RUN pip install poetry

# Copy our pyproject.toml file first to use Docker cache efficiently
COPY ./pyproject.toml /app/

# Install dependencies without creating a virtual environment inside the container
RUN poetry config virtualenvs.create false && poetry install --only main

# Copy the rest of our application
COPY . /app

# Run the application
CMD ["btvep", "start", "--port", "8000"]