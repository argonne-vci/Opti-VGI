# Use an official Python runtime as a parent image
FROM python:3.12

# Set the working directory in the container
WORKDIR /usr/src/app

# Install optivgi from PyPi, see comments below to install from local source
RUN pip install --no-cache-dir optivgi
# To install from local source, build using `python -m build` and copy the wheel to this directory
# COPY optivgi-1.0.0-py3-none-any.whl .
# RUN pip install --no-cache-dir optivgi-1.0.0-py3-none-any.whl

# Copy the example requirements.txt into the container at /usr/src/app
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the test server to run the example
COPY test_server.py .

# Copy the current directory contents into the container at /usr/src/app
COPY src/ .

# Copy the environment variables
COPY example.env ./.env

# Set the default command to execute
# when creating a new container
ENTRYPOINT ["/bin/sh", "-c", "python test_server.py & sleep 1 && python app.py"]
