HTTP API Example
================

Location: `./examples/http-api/`

This example demonstrates how to integrate Opti-VGI with an external system
using a simple HTTP API and WebSockets for notifications.

Components
----------
*   `src/translation/api.py`: A `Translation` implementation (`TranslationAPI`) that interacts with a mock server via HTTP requests (`requests` library).
*   `src/translation/listener_threads.py`: A thread that listens for WebSocket events (e.g., new reservations) from the mock server.
*   `src/app.py`: The main application entry point that sets up and runs the `scm_worker` and listener threads.
*   `test_server.py`: A mock HTTP and WebSocket server that simulates the external system (CSMS).
*   `Dockerfile`: Defines how to build a Docker image for the example.
*   `example.env`: Configuration file for ports and station groups.
*   `requirements.txt`: Python dependencies for the example.

Running with Docker
-------------------
You can run this example using Docker. There are two main ways: using the Opti-VGI version published on PyPI (simplest) or using a local build of Opti-VGI (useful for testing changes).


**Option 1: Running with Opti-VGI from PyPI (Default & Easiest)**

This method uses the `Dockerfile` as-is, which installs the latest stable `optivgi` package from the Python Package Index (PyPI).

1.  **Navigate to Example Directory**: Change into the example's directory:

    .. code-block:: bash

      cd ./examples/http-api/


2.  **Build Docker Image**: Build the image using the default Dockerfile:

    .. code-block:: bash

      docker build -t optivgi-http-example .

    *(This command will download and install `optivgi` from PyPI during the build process)*

3.  **Run Docker Container**: Run the image:

    .. code-block:: bash

      docker run --rm -it --name optivgi_http_example optivgi-http-example

    This will start the mock server and the Opti-VGI application within the container using the PyPI version of Opti-VGI. You should see log output from both. Press `Ctrl+C` to stop.


**Option 2: Running with a Local Opti-VGI Build**

Use this method if you have made local changes to the main Opti-VGI library that you want to test within this example, or if you need a version not yet published to PyPI.

1.  **Build Opti-VGI Wheel**: First, build the distribution package for Opti-VGI itself from the *project root directory* (one level above `examples/`):

    .. code-block:: bash

       pip install --upgrade build
       python -m build

    This creates files in the `dist/` directory (e.g., `optivgi-1.0.0-py3-none-any.whl`).

2.  **Copy Wheel**: Copy the generated `.whl` file into the `./examples/http-api/` directory.

    .. code-block:: bash

       cp dist/optivgi-*.whl ./examples/http-api/

3.  **Modify Dockerfile**: The provided `Dockerfile` installs Opti-VGI from PyPI by default. To install from the local wheel you just copied, uncomment the relevant lines in `./examples/http-api/Dockerfile` and comment out the PyPI install line:

    .. code-block:: dockerfile

       # Comment this out:
       # RUN pip install --no-cache-dir optivgi

       # Uncomment these:
       COPY optivgi-*.whl .
       RUN pip install --no-cache-dir optivgi-*.whl

    *(Make sure the version in the filename matches)*

4.  **Build Docker Image**: Navigate to the example directory and build the image:

    .. code-block:: bash

       cd ./examples/http-api/
       docker build -t optivgi-http-example .

5.  **Run Docker Container**: Run the image:

    .. code-block:: bash

       docker run --rm -it --name optivgi_http_example optivgi-http-example

    This will start the mock server and the Opti-VGI application within the container. You should see log output from both. Press Ctrl+C to stop.