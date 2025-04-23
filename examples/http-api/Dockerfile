# Copyright 2025 UChicago Argonne, LLC All right reserved
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://github.com/argonne-vci/Opti-VGI/blob/main/LICENSE
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Use an official Python runtime as a parent image
FROM python:3.12

# Set the working directory in the container
WORKDIR /usr/src/app

# Install optivgi from PyPi, see comments below to install from local source
RUN pip install --no-cache-dir optivgi
# To install from local source, build using `python -m build` and copy the wheel to this directory
# COPY optivgi-1.0.0-py3-none-any.whl .
# RUN pip install --no-cache-dir optivgi-1.0.0-py3-none-any.whl

# Copy the requirements.txt into the container at /usr/src/app
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
