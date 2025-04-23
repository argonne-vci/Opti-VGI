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
#
# pylint: disable=missing-module-docstring
import os
import asyncio
import logging
from queue import Queue
from datetime import datetime

import websockets


async def listen_websocket(event_queue: Queue):
    """Start a WebSocket client and listen for messages"""
    port = os.getenv('WEBSOCKET_PORT')
    assert port, f'WEBSOCKET_PORT({port}) environment variable must be set'
    endpoint = f'ws://localhost:{port}'

    logging.info("Trying to connect to the WebSocket server(%s) at %s", endpoint, datetime.now())
    async with websockets.connect(endpoint) as websocket:
        logging.info("Connected to the WebSocket server(%s) at %s", endpoint, datetime.now())
        while True:
            # Wait for the next message
            msg = await websocket.recv()

            logging.info("Message received (%s) at %s", str(msg), datetime.now())
            event_queue.put("Reservation Event on Listener")


def reservation_listener_thread(event_queue: Queue):
    """
    This function is used to create a dedicated thread for the reservation listener.
    This thread will listen to the WebSocket server and put the events in the event queue.
    :param event_queue: Queue to put the events
    """
    # Create a dedicated event loop for this thread
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Run the asynchronous listener on this thread
    loop.run_until_complete(listen_websocket(event_queue))
