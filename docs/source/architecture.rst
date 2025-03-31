Architecture Overview
=====================

Opti-VGI is designed with a modular architecture to separate concerns:

Core Components
---------------

*   **Translation Layer (`optivgi.translation`)**: Defines the interface (`Translation` abstract class) for communication with external systems (like a CSMS). Concrete implementations handle fetching EV data, power constraints, and sending charging commands.
*   **SCM Runner (`optivgi.scm_runner`)**: Orchestrates the main scheduling logic. It uses a `Translation` implementation to get inputs, passes them to an `Algorithm` implementation, and sends the results back via the `Translation` layer.
*   **SCM Algorithm (`optivgi.scm.algorithm`)**: Defines the interface (`Algorithm` abstract class) for different charging optimization strategies. Concrete implementations (`PulpNumericalAlgorithm`, `GoAlgorithm`) contain the core optimization logic.
*   **EV Data Structure (`optivgi.scm.ev`)**: Defines the `EV` dataclass used throughout the system to represent electric vehicles and their charging parameters/state.
*   **Worker Threads (`optivgi.threads`)**: Provides helper functions (`timer_thread_worker`, `scm_worker`) to run the SCM logic periodically or in response to events in background threads.
*   **Utilities (`optivgi.utils`)**: Contains helper functions, like date/time rounding.

Execution Flow
--------------

1.  An event (e.g., timer, external trigger due to new reservation) is placed on a queue.
2.  The `scm_worker` thread picks up the event.
3.  It instantiates the configured `Translation` and `Algorithm` classes.
4.  It calls `scm_runner`, passing the translation and algorithm classes.
5.  `scm_runner` uses the `Translation` object to:
    *   Get EV data (`get_evs`).
    *   Get power constraints (`get_peak_power_demand`).
6.  `scm_runner` instantiates the `Algorithm` with the fetched data.
7.  It calls the algorithm's `calculate` method to determine charging schedules.
8.  It retrieves the charging profiles (`get_charging_profiles`).
9.  It uses the `Translation` object to send the profiles to the external system (`send_power_to_evs`).

