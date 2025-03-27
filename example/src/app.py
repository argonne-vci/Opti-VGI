import time
import threading
import logging
from queue import Queue

from dotenv import load_dotenv

from optivgi.threads import timer_thread_worker, scm_worker
# from optivgi.scm.pulp_numerical_algorithm import PulpNumericalAlgorithm
from optivgi.scm.go_algorithm import GoAlgorithm

from example_translation.api import TranslationAPI
from example_translation.listener_threads import reservation_listener_thread


logging.basicConfig(
    format='%(asctime)s [Example App] %(levelname)-8s %(message)s',
    level=logging.INFO,
    datefmt='%Y-%m-%d %H:%M:%S')

load_dotenv()


def main():
    """
    Main function to start the threads and run the application.
    This function will start the OptiVGI threads, and any other listener threads.
    """
    # Event queue for worker threads
    event_queue = Queue()

    event_queue.put('Start')

    # Creating threads
    timer_thread = threading.Thread(target=timer_thread_worker, args=(event_queue,))
    # scm_worker_thread = threading.Thread(target=scm_worker, args=(event_queue, TranslationAPI, PulpNumericalAlgorithm))
    scm_worker_thread = threading.Thread(target=scm_worker, args=(event_queue, TranslationAPI, GoAlgorithm))
    listener_thread = threading.Thread(target=reservation_listener_thread, args=(event_queue,))

    logging.info('Starting threads...')
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
        timer_thread.join()
        listener_thread.join()
        logging.info('Threads successfully stopped.')


if __name__ == "__main__":
    main()
