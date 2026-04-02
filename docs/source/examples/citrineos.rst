CitrineOS Integration
=====================

This example demonstrates Opti-VGI integrated with `CitrineOS <https://github.com/citrineos/citrineos-core>`_,
an open-source OCPP 1.6J-compliant Charging Station Management System (CSMS). The demo
runs a multi-service Docker stack that simulates six EV charging stations connecting to
CitrineOS, with Opti-VGI performing smart charging optimization in real time.

The key concept illustrated is **curtailment**: when aggregate EV demand exceeds the site
power limit, the optimizer must reduce individual charging allocations. In the default
scenario, six EVs each request 7.2 kW (43.2 kW total), but the site limit is only 30 kW.
Opti-VGI's scheduling algorithm distributes available power fairly across all connected
vehicles while respecting each EV's minimum and maximum charge rates.

See :doc:`/architecture` for details on the core Opti-VGI scheduling framework.

Components
----------

*   ``docker-compose.yml`` -- Multi-service stack definition (CitrineOS, PostgreSQL, RabbitMQ, Hasura, Opti-VGI, Simulator)
*   ``src/translation/citrineos.py`` -- ``CitrineOSTranslation`` class implementing ``get_evs`` and ``send_power_to_evs`` for the CitrineOS REST API
*   ``src/app.py`` -- Entry point with ``LoggingTranslation`` wrapper and RabbitMQ listener for new-session triggers
*   ``simulator/`` -- OCPP 1.6J charger simulator that creates six virtual charging stations
*   ``simulator/scenarios/default.json`` -- Default demo scenario configuration (staggered EV arrivals)
*   ``example.env`` -- Environment variable configuration (copy to ``.env`` before running)
*   ``verify.py`` -- Automated curtailment verification script (checks profiles, sessions, aggregate power, curtailment)

Running the Demo
----------------

**Prerequisites:**

*   Docker and Docker Compose (v2)

**Steps:**

1.  Navigate to the example directory:

    .. code-block:: bash

       cd examples/citrineos

2.  Copy the example environment file:

    .. code-block:: bash

       cp example.env .env

3.  Build and start the stack:

    .. code-block:: bash

       docker compose up --build --attach opti-vgi --attach simulator

The ``--attach`` flags show output from only the Opti-VGI optimizer and the charger simulator,
keeping infrastructure services (PostgreSQL, RabbitMQ, CitrineOS, Hasura) silent. Services
start in dependency order automatically. EVs arrive at staggered 60-second intervals, and log
output shows arrivals, departures, and curtailment events when aggregate demand exceeds the
site limit.

Press ``Ctrl+C`` to stop all services.

Demo Scenario
-------------

The default scenario (``scenarios/default.json``) simulates six EVs arriving at staggered
60-second intervals on six separate charging stations. Each EV has a maximum charge rate of
7.2 kW. With a site power limit of 30 kW, curtailment activates once enough EVs are
connected that their combined demand exceeds the limit.

For example, when the first four EVs are connected, aggregate demand is 4 x 7.2 = 28.8 kW,
which is under the 30 kW limit -- no curtailment needed. Once the fifth EV arrives
(5 x 7.2 = 36.0 kW requested), the optimizer must reduce allocations. With all six EVs
connected (6 x 7.2 = 43.2 kW requested), each EV receives approximately 5.0 kW to stay
within the 30 kW site limit.

How Curtailment Works
---------------------

Opti-VGI runs a scheduling loop that is triggered by new EV session events arriving via
RabbitMQ. On each cycle, the optimizer:

1.  Queries CitrineOS for all active charging transactions
2.  Reads each EV's energy needs, min/max power, and timing constraints
3.  Runs the ``GoAlgorithm`` optimization to allocate power within the site limit
4.  Sends a ``SetChargingProfile`` command to CitrineOS for each EV with its allocated power

The following diagrams show the service topology and the scheduling data flow.

.. mermaid::
   :align: center
   :caption: CitrineOS Demo Service Topology

   graph TD
       simulator["Charger Simulator<br/>(6 OCPP stations)"]
       citrineos["CitrineOS CSMS<br/>(v1.8.3)"]
       optivgi["Opti-VGI<br/>(Smart Charging)"]
       db["PostgreSQL"]
       rabbitmq["RabbitMQ"]
       hasura["Hasura GraphQL"]

       simulator -->|"OCPP 1.6J<br/>WebSocket"| citrineos
       citrineos --> db
       citrineos -->|"Transaction events"| rabbitmq
       rabbitmq -->|"New session triggers"| optivgi
       optivgi -->|"REST API<br/>get_evs / SetChargingProfile"| citrineos
       optivgi -->|"GraphQL<br/>MeterValues"| hasura
       hasura --> db

.. mermaid::
   :align: center
   :caption: Scheduling Flow

   sequenceDiagram
       participant Sim as Simulator
       participant COS as CitrineOS
       participant RMQ as RabbitMQ
       participant OV as Opti-VGI

       Sim->>COS: BootNotification
       COS-->>Sim: Accepted
       Sim->>COS: StartTransaction
       COS->>RMQ: Transaction event
       RMQ->>OV: New session trigger
       OV->>COS: GET active transactions
       COS-->>OV: EV data
       OV->>OV: Run optimization (GoAlgorithm)
       OV->>COS: SetChargingProfile (per EV)
       COS-->>OV: Accepted

Environment Variables
---------------------

All configuration is done through environment variables defined in ``example.env``.
Copy it to ``.env`` and modify as needed.

**Service Ports**

.. list-table::
   :header-rows: 1
   :widths: 30 15 55

   * - Variable
     - Default
     - Description
   * - ``CITRINEOS_PORT``
     - ``8080``
     - CitrineOS REST API port exposed to host
   * - ``OCPP16_PORT``
     - ``8092``
     - OCPP 1.6J WebSocket port exposed to host
   * - ``HASURA_PORT``
     - ``8090``
     - Hasura GraphQL Engine port exposed to host
   * - ``OPERATOR_UI_PORT``
     - ``3000``
     - Operator dashboard port (if enabled)

**Simulator Configuration**

.. list-table::
   :header-rows: 1
   :widths: 30 15 55

   * - Variable
     - Default
     - Description
   * - ``STATION_IDS``
     - 6 stations
     - Comma-separated station identifiers (e.g., ``OPTIVGI-STATION-01,...,06``)
   * - ``CONNECTORS_PER_STATION``
     - ``2``
     - Number of OCPP connectors per station
   * - ``METER_VALUES_INTERVAL``
     - ``10``
     - Interval in seconds between MeterValues messages
   * - ``CITRINEOS_WS_URL``
     - ``ws://citrineos:8092``
     - WebSocket URL for OCPP connection (internal Docker network)
   * - ``SCENARIO_FILE``
     - ``scenarios/default.json``
     - Scenario file path; set to empty string for manual trigger mode
   * - ``SEED_ID_TAGS``
     - 6 tags
     - Comma-separated idTags to seed in CitrineOS Authorizations table

**Opti-VGI Configuration**

.. list-table::
   :header-rows: 1
   :widths: 30 15 55

   * - Variable
     - Default
     - Description
   * - ``SITE_POWER_LIMIT_KW``
     - ``30``
     - Site-wide power limit in kW for curtailment
   * - ``VOLTAGE``
     - ``240``
     - Voltage (V) for watt/ampere conversions
   * - ``STATION_GROUPS``
     - ``default``
     - Station group names for Opti-VGI scheduling

**Internal URLs**

.. list-table::
   :header-rows: 1
   :widths: 30 15 55

   * - Variable
     - Default
     - Description
   * - ``CITRINEOS_API_URL``
     - ``http://citrineos:8080``
     - CitrineOS REST API URL (internal Docker network)
   * - ``HASURA_URL``
     - ``http://graphql-engine:8080``
     - Hasura GraphQL URL (internal Docker network)
   * - ``AMQP_URL``
     - ``amqp://guest:guest@amqp-broker:5672``
     - RabbitMQ AMQP connection URL

**Per-Connector EV Configuration**

Each connector is configured with a set of ``CONN_XX_*`` variables where ``XX`` is a
zero-padded index (01 through 06 in the default setup). Each ``CONN_XX`` maps to the
Nth station in ``STATION_IDS``.

.. list-table::
   :header-rows: 1
   :widths: 35 15 50

   * - Variable Pattern
     - Example
     - Description
   * - ``CONN_XX_ENERGY_NEEDED_KWH``
     - ``30``
     - Energy needed by the EV in kWh
   * - ``CONN_XX_MAX_POWER_KW``
     - ``7.2``
     - Maximum charge rate in kW
   * - ``CONN_XX_MIN_POWER_KW``
     - ``1.4``
     - Minimum charge rate in kW
   * - ``CONN_XX_ARRIVAL_TIME``
     - ``06:00``
     - Simulated arrival time (HH:MM)
   * - ``CONN_XX_DEPARTURE_TIME``
     - ``14:00``
     - Simulated departure time (HH:MM)

Operator Dashboard
------------------

While the demo is running, open the CitrineOS operator UI to see charging stations, active
transactions, and charging profiles in real time.

*   **URL:** ``http://localhost:3000`` (or your ``OPERATOR_UI_PORT``)
*   **Username:** ``admin@citrineos.com``
*   **Password:** ``CitrineOS!``

The Hasura GraphQL console is also available at ``http://localhost:8090`` (or your
``HASURA_PORT``) for direct database queries (e.g., browsing the ``Transactions`` or
``ChargingProfiles`` tables).

Expected Output
---------------

When the demo is running, the logs show only meaningful events — EV arrivals,
departures, and curtailment transitions. Representative output:

.. code-block:: text

   [Opti-VGI] INFO     EV 1 arrived — max 7.20 kW
   [Opti-VGI] INFO     OCPP event: StartTransaction
   [Opti-VGI] INFO     EV 2 arrived — max 7.20 kW
   [Opti-VGI] INFO     EV 3 arrived — max 7.20 kW
   [Opti-VGI] INFO     EV 4 arrived — max 7.20 kW
   [Opti-VGI] INFO     EV 5 arrived — max 7.20 kW
   [Opti-VGI] INFO     CURTAILMENT ON — 5 EVs requesting 36.0 kW, site limit 30.0 kW, allocated 30.0 kW
   [Opti-VGI] INFO       EV 1: 7.00 kW / 7.20 kW max
   [Opti-VGI] INFO       EV 2: 7.20 kW / 7.20 kW max
   [Opti-VGI] INFO       EV 3: 7.20 kW / 7.20 kW max
   [Opti-VGI] INFO       EV 4: 1.40 kW / 7.20 kW max
   [Opti-VGI] INFO       EV 5: 7.20 kW / 7.20 kW max

You can verify that curtailment is working correctly by running the automated
verification script after the demo has run for a few minutes:

.. code-block:: bash

   python verify.py

Representative output:

.. code-block:: text

   === Opti-VGI Curtailment Verification ===

   Config: url=http://localhost:8090, site_limit=30.0 kW, voltage=240.0 V

   [PASS] Check 1: Charging profiles sent -- Found 6 charging profiles (need >= 3)
   [PASS] Check 2: Concurrent sessions -- Found 6 profiles with active allocations (need >= 3)
   [PASS] Check 3: Aggregate within limit -- Aggregate in latest cycle (6 EVs, ...): 30.0 kW <= 30.0 kW limit (+0.8 kW rounding tolerance)
   [PASS] Check 4: Curtailment occurred -- Found 60 curtailed profiles in history (min was 1.44 kW, max rate 7.20 kW)

   Result: 4/4 checks passed -- PASS

Add ``--plot`` to generate a stacked area chart showing per-EV power allocation over
time, with the site limit line and over-limit periods highlighted in red:

.. code-block:: bash

   python verify.py --plot

This saves ``curtailment_plot.png`` in the current directory. The plot shows each EV's
allocated power as a colored band, making it easy to see how the optimizer redistributes
power when curtailment is active.

Customization
-------------

You can modify the demo behavior by changing environment variables in your ``.env`` file:

*   **``SITE_POWER_LIMIT_KW``** -- Increase or decrease the site limit to see more or less curtailment. For example, setting it to ``50`` eliminates curtailment with six 7.2 kW EVs, while ``20`` forces more aggressive reduction.
*   **``CONN_XX_MAX_POWER_KW``** -- Change individual EV max charge rates to create heterogeneous fleets.
*   **``SCENARIO_FILE``** -- Set to an empty string (``SCENARIO_FILE=``) to disable automatic EV arrivals and use manual trigger mode instead.
*   **``STATION_IDS``** -- Add or remove station IDs to change the number of simulated chargers. Remember to add corresponding ``CONN_XX_*`` variables for new stations.

Troubleshooting
---------------

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Issue
     - Solution
   * - Port 8080 already in use
     - Change ``CITRINEOS_PORT`` in ``.env`` to an available port (e.g., ``8081``)
   * - CitrineOS takes 60+ seconds to start
     - This is normal on first run due to database migrations. The health check has a 60-second ``start_period`` configured. Wait for the simulator to report successful connections.
   * - Docker memory issues with 8+ containers
     - Allocate at least 4 GB of memory to Docker Desktop (Settings > Resources)
   * - Simulator connects before CitrineOS is ready
     - This is handled automatically by Docker health checks and ``depends_on`` conditions. The simulator retries connections until CitrineOS is healthy.
   * - ``maxConnectionsPerTenant`` error in CitrineOS logs
     - The docker-compose configuration patches this automatically via an entrypoint ``sed`` command. If you see this error, ensure you are using the provided ``docker-compose.yml`` without modifications to the CitrineOS entrypoint.
