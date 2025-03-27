import time
import logging
import traceback
from queue import Queue
from datetime import datetime
from typing import Type

from .scm_runner import scm_runner
from .translation import Translation
from .scm.algorithm import Algorithm


def timer_thread_worker(event_queue: Queue):
    """Thread that sends a timer event every minute"""
    while True:
        current_time = time.time()
        delay = 60 - (current_time % 60)
        time.sleep(delay) # Sleep until the top of the next minute
        event_queue.put("Timer Event")


# SCM worker thread function
def scm_worker(event_queue: Queue, translation_cls: Type[Translation], algorithm_cls: Type[Algorithm]):
    """Thread that processes events from the event queue and runs the SCM worker"""
    with translation_cls() as translation:
        while True:
            event = event_queue.get()
            if event is None:
                break  # Allows the thread to be stopped.
            logging.info("Processing event %s at %s", event, datetime.now())
            try:
                scm_runner(translation, algorithm_cls)
            except Exception as e: # pylint: disable=broad-except
                logging.error("Error processing event %s: %s", event, repr(e))
                logging.error(traceback.format_exc())
            event_queue.task_done()
