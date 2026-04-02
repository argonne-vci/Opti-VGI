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
# pylint: disable=missing-module-docstring,wrong-import-order
import time
import threading
import logging
from queue import Queue

from dotenv import load_dotenv

from optivgi.threads import timer_thread_worker, scm_worker
from optivgi.scm.go_algorithm import GoAlgorithm

from translation.citrineos import CitrineOSTranslation
from translation.listener_threads import rabbitmq_listener_thread


# Root logger at WARNING to suppress core library per-cycle noise
# (optivgi uses logging.info() on root logger, pika does too)
logging.basicConfig(
    format='%(asctime)s [Opti-VGI] %(levelname)-8s %(message)s',
    level=logging.WARNING,
    datefmt='%Y-%m-%d %H:%M:%S')

# App and translation loggers at INFO — only our meaningful events
for _name in (__name__, 'translation.citrineos', 'translation.listener_threads'):
    logging.getLogger(_name).setLevel(logging.INFO)

logger = logging.getLogger(__name__)

load_dotenv()


class LoggingTranslation(CitrineOSTranslation):
    """Subclass that adds state-change logging for demo observability.

    Only logs meaningful events: EV arrivals, departures, and curtailment
    transitions — not every SCM cycle.
    """

    def __init__(self):
        super().__init__()
        self._previous_ev_ids: set[int] = set()
        self._was_curtailed: bool = False

    def get_evs(self, group_name: str):
        """Log EV arrivals and departures, then delegate to parent."""
        evs, voltage = super().get_evs(group_name)

        current_ids = {ev.ev_id for ev in evs}
        new_ids = current_ids - self._previous_ev_ids
        departed_ids = self._previous_ev_ids - current_ids
        if new_ids:
            for ev in evs:
                if ev.ev_id in new_ids:
                    logger.info("EV %d arrived — max %.2f kW", ev.ev_id, ev.max_power)
        if departed_ids:
            for ev_id in departed_ids:
                logger.info("EV %d departed", ev_id)
        self._previous_ev_ids = current_ids

        return evs, voltage

    def send_power_to_evs(self, powers, unit=None):
        """Log only when curtailment state changes."""
        aggregate = sum(ev.power[0] for ev in powers)
        requested_total = sum(ev.max_power for ev in powers)
        is_curtailed = requested_total > self.site_power_limit

        if is_curtailed and not self._was_curtailed:
            logger.info(
                "CURTAILMENT ON — %d EVs requesting %.1f kW, site limit %.1f kW, "
                "allocated %.1f kW",
                len(powers), requested_total, self.site_power_limit, aggregate,
            )
            for ev in powers:
                logger.info("  EV %d: %.2f kW / %.2f kW max", ev.ev_id, ev.power[0], ev.max_power)
        elif not is_curtailed and self._was_curtailed:
            logger.info(
                "CURTAILMENT OFF — %d EVs using %.1f kW (limit %.1f kW)",
                len(powers), aggregate, self.site_power_limit,
            )
        self._was_curtailed = is_curtailed

        super().send_power_to_evs(powers, unit)


def main():
    """
    Main function to start the threads and run the application.
    Starts Opti-VGI threads (timer, SCM worker) and the RabbitMQ listener
    for CitrineOS OCPP event integration.
    """
    # Event queue for worker threads
    event_queue = Queue()

    event_queue.put('Start')

    # Creating threads
    timer_thread = threading.Thread(
        target=timer_thread_worker, args=(event_queue,), daemon=True)
    scm_worker_thread = threading.Thread(
        target=scm_worker, args=(event_queue, LoggingTranslation, GoAlgorithm))
    listener_thread = threading.Thread(
        target=rabbitmq_listener_thread, args=(event_queue,), daemon=True)

    logging.info('Starting Opti-VGI CitrineOS integration...')
    # Starting threads
    scm_worker_thread.start()
    timer_thread.start()
    listener_thread.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logging.info('Stopping threads...')
        event_queue.put(None)  # Signal the worker to stop
        scm_worker_thread.join()
        logging.info('Threads successfully stopped.')


if __name__ == "__main__":
    main()
