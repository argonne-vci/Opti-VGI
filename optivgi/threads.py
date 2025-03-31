"""
Provides worker thread functions for running Opti-VGI tasks asynchronously.

These functions are designed to be run in separate threads, allowing the main
application to remain responsive while handling periodic scheduling tasks or
reacting to external events.
"""
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
    """
    Worker function for a timer thread.

    This function sleeps until the start of the next minute and then puts a
    "Timer Event" message onto the provided event queue. It runs in an infinite loop.

    Args:
        event_queue: The queue to which timer events will be added.
    """
    while True:
        current_time = time.time()
        delay = 60 - (current_time % 60)
        time.sleep(delay) # Sleep until the top of the next minute
        event_queue.put("Timer Event")


# SCM worker thread function
def scm_worker(event_queue: Queue, translation_cls: Type[Translation], algorithm_cls: Type[Algorithm]):
    """
    Worker function for the main Smart Charging Management (SCM) logic.

    This function continuously monitors an event queue. When an event is received,
    it instantiates the provided Translation and Algorithm classes and executes
    the main SCM logic using `scm_runner`. It handles potential exceptions during
    the process and ensures the event queue task is marked as done.

    It operates within the context manager provided by the `Translation`.

    Args:
        event_queue: The queue from which events are retrieved. Processing stops
                     if `None` is received.
        translation_cls: The class type of the Translation layer implementation to use.
                         Must inherit from `optivgi.translation.Translation`.
        algorithm_cls: The class type of the SCM Algorithm implementation to use.
                       Must inherit from `optivgi.scm.algorithm.Algorithm`.
    """
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
