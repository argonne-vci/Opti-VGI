"""
A combined HTTP & WebSocket server that:
- Serves HTTP endpoints for:
  1) GET /peak_power_demand      -> Reply to 'TranslationAPI.get_peak_power_demand'
  2) GET /evs                    -> Reply to active EVS in 'TranslationAPI.get_evs'
  3) GET /future_evs             -> Reply to future EVS in 'TranslationAPI.get_evs'
  4) POST /powers                -> Reply to 'TranslationAPI.send_power_to_evs'
- Serves a WebSocket endpoint to publish new reservations
"""
import os
import asyncio
import http.server
import json
import logging
import socketserver
import threading
import random
from datetime import datetime, timedelta, UTC
from urllib.parse import urlparse, parse_qs
from typing import Optional

import websockets
from dotenv import load_dotenv


logging.basicConfig(
    format='%(asctime)s [Test Server] %(levelname)-8s %(message)s',
    level=logging.INFO,
    datefmt='%Y-%m-%d %H:%M:%S')

load_dotenv()


# ------------------------------
# WebSocket Server
# ------------------------------
# Global container to hold connected WebSocket clients
connected_websockets = set()

async def reservations_handler(websocket):
    """
    WebSocket handler that accepts connections and
    listens for incoming messages (if any).
    We use this just to keep track of connected clients
    so we can push 'new reservation' events to them.
    """
    logging.info("WebSocket client connected.")
    connected_websockets.add(websocket)
    try:
        async for message in websocket:
            # If the client sends any message, you could handle it here.
            logging.info("Received from WebSocket client: %s", message)
            # Echo or do nothing in this example
            await websocket.send(f"Server echo: {message}")
    except websockets.ConnectionClosed:
        logging.info("WebSocket client disconnected.")
    finally:
        connected_websockets.remove(websocket)


async def start_websocket_server(stop_event: Optional[threading.Event] = None):
    """
    Start the WebSocket server. This runs inside an event loop in a separate thread.
    """
    port = os.getenv("WEBSOCKET_PORT")
    assert port, "WEBSOCKET_PORT environment variable must be set"
    assert port.isdigit(), "WEBSOCKET_PORT must be a valid port number"

    async with websockets.serve(reservations_handler, "0.0.0.0", int(port)):
        logging.info("WebSocket server started at ws://localhost:%s", port)
        # Keep the server running until we signal it to stop.
        while not stop_event or not stop_event.is_set():
            await asyncio.sleep(15)
            if random.random() < 0.25:
                await broadcast_reservation({
                    "ev_id": random.randint(1, 100),
                })


async def broadcast_reservation(res_data: dict):
    """
    Broadcast a new reservation event to all connected WebSocket clients.
    """
    if not connected_websockets:
        logging.info("No WebSocket clients to broadcast to.")
        return

    message_str = json.dumps({
        "type": "NEW_RESERVATION",
        "data": res_data
    })
    logging.info("Broadcasting new reservation to WebSocket clients...")
    await asyncio.gather(*(ws.send(message_str) for ws in connected_websockets))


# ------------------------------
# HTTP Server
# ------------------------------
class TranslationHTTPRequestHandler(http.server.BaseHTTPRequestHandler):
    """
    Minimal HTTP server that routes:
      GET  /peak_power_demand
      GET  /evs
      GET  /future_evs
      POST /powers
    """
    def __init__(self, *args, **kwargs):
        self.group1 = next(filter(bool, map(str.strip, os.getenv('STATION_GROUPS', '').split(','))))
        super().__init__(*args, **kwargs)

    def _send_json_response(self, data, status_code=200):
        """Utility to send a JSON response."""
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))

    def do_GET(self):
        """Handle GET requests."""
        parsed_path = urlparse(self.path)
        query_params = parse_qs(parsed_path.query)

        if parsed_path.path == "/peak_power_demand":
            # This is a response for 'get_peak_power_demand(...)'
            now = datetime.fromisoformat(query_params['timestamp'][0])
            group_name = query_params['group_name'][0]
            response_data = {
                now.isoformat(): 10,
                (now + timedelta(hours=1)).isoformat(): 20,
                (now + timedelta(hours=3)).isoformat(): 10,
                (now + timedelta(hours=6)).isoformat(): 30,
            } if (group_name == self.group1) else {
                now.isoformat(): 0,
            }
            self._send_json_response(response_data)

        elif parsed_path.path == "/evs":
            # This is a response for 'get_evs(...)'
            now = datetime.now(UTC)
            group_name = query_params['group_name'][0]
            def ev_factory(ev_id, duration=timedelta(hours=1), energy_needed=20):
                return {
                    "ev_id": ev_id,
                    "station_id": ev_id,
                    "connector_id": random.choice([1, 2]),
                    "min_power": 3.,
                    "max_power": 7.,
                    "arrival_time": now.isoformat(),
                    "departure_time": (now + duration).isoformat(),
                    "energy_needed": energy_needed
                }
            response_data = {
                "evs": [
                    ev_factory(1, duration=timedelta(hours=1), energy_needed=20),
                    ev_factory(2, duration=timedelta(hours=2), energy_needed=30),
                ],
                "voltage": 200.0
            } if (group_name == self.group1) else {}
            self._send_json_response(response_data)

        elif parsed_path.path == "/future_evs":
            # This is a response for 'get_evs(...)'
            now = datetime.now(UTC)
            group_name = query_params['group_name'][0]
            def future_ev_factory(ev_id, start_time=now, duration=timedelta(hours=1), energy_needed=20):
                return {
                    "ev_id": ev_id,
                    "station_id": ev_id,
                    "connector_id": random.choice([1, 2]),
                    "min_power": 3.,
                    "max_power": 7.,
                    "arrival_time": start_time.isoformat(),
                    "departure_time": (start_time + duration).isoformat(),
                    "energy_needed": energy_needed
                }
            future_start_time = now + timedelta(hours=1)
            response_data = {
                "future_evs": [
                    future_ev_factory(3, future_start_time, duration=timedelta(hours=1), energy_needed=20),
                    future_ev_factory(4, future_start_time, duration=timedelta(hours=2), energy_needed=30),
                ],
                "voltage": 200.0
            } if (group_name == self.group1) else {}
            self._send_json_response(response_data)

        else:
            self._send_json_response({"error": "Not Found"}, 404)

    def do_POST(self):
        """Handle POST requests."""
        parsed_path = urlparse(self.path)

        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length).decode('utf-8') if content_length > 0 else "{}"
        try:
            request_data = json.loads(body)
        except json.JSONDecodeError:
            request_data = {}

        if parsed_path.path == "/powers":
            # This is a response for 'send_power_to_evs(...)'
            # request_data might contain a structure like: { ev_id: {...charging profile...}, ... }
            logging.info("Received power allocation: %s", json.dumps(request_data))
            # ... actual logic to handle sending power to EVs ...
            self._send_json_response({"status": "Power sent"})

        else:
            self._send_json_response({"error": "Not Found"}, 404)


def start_http_server(stop_event: Optional[threading.Event] = None):
    """
    Starts a blocking HTTP server on the given port in the current thread.
    It will stop if `stop_event` is set (by shutting down the server).
    """
    port = os.getenv("API_PORT")
    assert port, "API_PORT environment variable must be set"
    assert port.isdigit(), "API_PORT must be a valid port number"

    handler = TranslationHTTPRequestHandler
    with socketserver.TCPServer(("", int(port)), handler) as httpd:
        logging.info("HTTP server started on http://0.0.0.0:%s", port)
        # Serve until stop_event is triggered (or user hits Ctrl+C)
        while not stop_event or not stop_event.is_set():
            httpd.handle_request()  # handle one request at a time
        logging.info("HTTP server shutting down.")


# ------------------------------
# Main Entry
# ------------------------------
def main():
    stop_event = threading.Event()

    # 1) Start the HTTP server in a dedicated thread
    http_thread = threading.Thread(
        target=start_http_server,
        args=(stop_event,),
        daemon=True
    )
    http_thread.start()

    # 2) Start the WebSocket server in the main asyncio event loop (on another thread).
    loop = asyncio.new_event_loop()
    ws_thread = threading.Thread(
        target=lambda: loop.run_until_complete(start_websocket_server(stop_event)),
        daemon=True
    )
    ws_thread.start()

    logging.info("Servers are running. Press Ctrl+C to stop.")

    try:
        # Wait until the user stops the program (Ctrl + C)
        while True:
            threading.Event().wait(1)
    except KeyboardInterrupt:
        logging.info("Stop signal received.")
        stop_event.set()
        # Give servers time to shut down gracefully
        ws_thread.join()
        http_thread.join()


if __name__ == "__main__":
    main()
