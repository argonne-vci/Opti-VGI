# CitrineOS Integration Example

Demonstrates Opti-VGI smart charging integrated with
[CitrineOS](https://github.com/citrineos/citrineos-core), an open-source
OCPP 1.6J charge station management system.

## Prerequisites

- **Docker** and **Docker Compose** (v2)
- **4+ GB memory** allocated to Docker (the stack runs 8+ containers)

## Quick Start

```bash
cd examples/citrineos
cp example.env .env
docker compose up --build --attach opti-vgi --attach simulator
```

The `--attach` flags show output from only the Opti-VGI optimizer and charger
simulator, keeping infrastructure services silent. 6 EVs arrive at staggered
60-second intervals. Watch for:

- **EV arrived** — each new EV connecting
- **CURTAILMENT ON** — when aggregate demand exceeds the 30 kW site limit
- **CURTAILMENT OFF** — when EVs depart and demand drops below the limit
- **EV departed** — each EV disconnecting

## Operator Dashboard

While the demo is running, open the CitrineOS operator UI to see charging
stations, active transactions, and charging profiles in real time.

- **URL:** http://localhost:3000 (or your `OPERATOR_UI_PORT`)
- **Username:** `admin@citrineos.com`
- **Password:** `CitrineOS!`

The Hasura GraphQL console is also available at http://localhost:8090 (or
your `HASURA_PORT`) for direct database queries.

## Verification

The full demo runs for ~15 minutes. After it completes, verify curtailment
correctness (run from another terminal while the stack is still up):

```bash
python verify.py
```

Add `--plot` to generate a chart showing per-EV power allocation over time
with the site limit and over-limit periods highlighted:

```bash
python verify.py --plot
```

This saves `curtailment_plot.png` in the current directory.

## Environment Variables

All configuration lives in `.env` (copy from `example.env`). Key variables
are listed below, grouped by function.

### Service Ports

| Variable | Default | Description |
|----------|---------|-------------|
| `CITRINEOS_PORT` | `8080` | CitrineOS REST API port (host) |
| `OCPP16_PORT` | `8092` | OCPP 1.6J WebSocket port (host) |
| `HASURA_PORT` | `8090` | Hasura GraphQL console port (host) |
| `OPERATOR_UI_PORT` | `3000` | Operator dashboard port (host) |

### Opti-VGI Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `SITE_POWER_LIMIT_KW` | `30` | Aggregate site power cap in kW |
| `VOLTAGE` | `240` | Nominal voltage for W/A conversions |
| `STATION_GROUPS` | `default` | Station group name for scheduling |

### Simulator Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `STATION_IDS` | `OPTIVGI-STATION-01,...,06` | Comma-separated station identifiers |
| `CONNECTORS_PER_STATION` | `2` | Connectors per simulated station |
| `METER_VALUES_INTERVAL` | `10` | Seconds between MeterValues messages |
| `CITRINEOS_WS_URL` | `ws://citrineos:8092` | WebSocket URL (internal network) |
| `SCENARIO_FILE` | `scenarios/default.json` | Scenario file path (empty = wait-for-trigger) |
| `SEED_ID_TAGS` | `OPTIVGI-01,...,06` | idTags seeded into CitrineOS Authorizations |

### Internal Service URLs

| Variable | Default | Description |
|----------|---------|-------------|
| `CITRINEOS_API_URL` | `http://citrineos:8080` | CitrineOS API (Docker internal) |
| `HASURA_URL` | `http://graphql-engine:8080` | Hasura GraphQL (Docker internal) |
| `AMQP_URL` | `amqp://guest:guest@amqp-broker:5672` | RabbitMQ AMQP broker URL |

### Per-Connector EV Configuration

Each `CONN_XX_*` group configures one EV. `CONN_01` maps to the first
station in `STATION_IDS`, `CONN_02` to the second, and so on.

| Variable | Default (CONN_01) | Description |
|----------|-------------------|-------------|
| `CONN_XX_ENERGY_NEEDED_KWH` | `30` | Energy required in kWh |
| `CONN_XX_MAX_POWER_KW` | `7.2` | Maximum charging power in kW |
| `CONN_XX_MIN_POWER_KW` | `1.4` | Minimum charging power in kW |
| `CONN_XX_ARRIVAL_TIME` | `06:00` | Simulated arrival time (HH:MM) |
| `CONN_XX_DEPARTURE_TIME` | `14:00` | Simulated departure time (HH:MM) |

Repeat for `CONN_02` through `CONN_06` with appropriate values.
See `example.env` for the full set of defaults.

## Documentation

Full guide with architecture diagrams, troubleshooting, and customization:
[CitrineOS Integration](https://argonne-vci.github.io/Opti-VGI/examples/citrineos.html)
