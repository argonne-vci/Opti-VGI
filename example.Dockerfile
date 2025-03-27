# Use an official Python runtime as a parent image
FROM python:3.12

# Set the working directory in the container
WORKDIR /usr/src/app

# Copy the main requirements.txt into the container at /usr/src/app
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the main source directory contents into the container at /usr/src/app
COPY optivgi optivgi

# Copy the example requirements.txt into the container at /usr/src/app
COPY example/requirements.txt .

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the test server to run the example
COPY example/test_server.py .

# Copy the current directory contents into the container at /usr/src/app
COPY example/src/ .

# Copy the environment variables
COPY example/example.env ./.env

# Set the default command to execute
# when creating a new container
ENTRYPOINT ["/bin/sh", "-c", "python test_server.py & sleep 1 && python app.py"]
