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
"""
RabbitMQ listener thread for CitrineOS OCPP event integration.

Consumes messages from the CitrineOS headers exchange, triggering
re-optimization on StartTransaction, StopTransaction, StatusNotification,
and externally-originated SetChargingProfile events. Filters out Opti-VGI's
own SetChargingProfile confirmations to prevent feedback loops.
"""
import logging
import os
import time
from queue import Queue

import pika

logger = logging.getLogger(__name__)

# OCPP actions that trigger re-optimization
# SetChargingProfile is excluded to avoid feedback loops — Opti-VGI is
# the sole source of charging profiles in this integration.
TRIGGER_ACTIONS = [
    "StartTransaction",
    "StopTransaction",
    "StatusNotification",
]


def rabbitmq_listener_thread(event_queue: Queue):
    """Listen to CitrineOS RabbitMQ headers exchange and enqueue OCPP events.

    Connects to the RabbitMQ broker, declares a headers exchange binding for
    each trigger action, and consumes messages. Opti-VGI's own
    SetChargingProfile confirmations are filtered out by checking the origin
    header.

    Runs in an infinite retry loop to handle broker restarts gracefully.

    Args:
        event_queue: Shared queue for signaling the SCM worker thread.
    """
    amqp_url = os.getenv("AMQP_URL", "amqp://guest:guest@amqp-broker:5672")

    while True:
        try:
            logger.info("Connecting to RabbitMQ at %s", amqp_url)
            params = pika.URLParameters(amqp_url)
            connection = pika.BlockingConnection(params)
            channel = connection.channel()

            # Declare the headers exchange (must match CitrineOS config)
            channel.exchange_declare(
                exchange="citrineos",
                exchange_type="headers",
                durable=False,
            )

            # Declare an exclusive auto-delete queue for this consumer
            result = channel.queue_declare(
                queue="optivgi-events",
                durable=False,
                auto_delete=True,
            )
            queue_name = result.method.queue

            # Bind for each trigger action using headers matching
            for action in TRIGGER_ACTIONS:
                channel.queue_bind(
                    exchange="citrineos",
                    queue=queue_name,
                    arguments={"x-match": "all", "action": action},
                )
                logger.info("Bound queue to action: %s", action)

            def on_message(ch, method, properties, _body):
                """Process an incoming OCPP event message."""
                headers = properties.headers or {}
                action = headers.get("action", "unknown")
                origin = headers.get("origin", "")

                # Filter out Opti-VGI's own SetChargingProfile confirmations
                if origin and "optivgi" in origin.lower():
                    logger.debug(
                        "Skipping self-originated message: action=%s origin=%s",
                        action, origin,
                    )
                    ch.basic_ack(delivery_tag=method.delivery_tag)
                    return

                if action in ("StartTransaction", "StopTransaction"):
                    logger.info("OCPP event: %s", action)
                else:
                    logger.debug("OCPP event: %s", action)
                event_queue.put(f"OCPP Event: {action}")
                ch.basic_ack(delivery_tag=method.delivery_tag)

            channel.basic_consume(
                queue=queue_name,
                on_message_callback=on_message,
            )

            logger.info("RabbitMQ listener started, consuming events...")
            channel.start_consuming()

        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("RabbitMQ connection error: %s. Retrying in 5s...", repr(e))
            time.sleep(5)
