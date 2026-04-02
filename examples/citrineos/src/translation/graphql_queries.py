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
Hasura GraphQL query strings for CitrineOS data access.

Queries target the CitrineOS Hasura GraphQL engine to fetch active transactions,
meter values, and connector status notifications.
"""

ACTIVE_TRANSACTIONS_QUERY = """
query ActiveTransactions {
    Transactions(where: {isActive: {_eq: true}}) {
        id
        transactionId
        stationId
        isActive
        startTime
        meterStart
        Connector {
            connectorId
        }
        MeterValues(order_by: {timestamp: desc}, limit: 1) {
            sampledValue
            timestamp
        }
    }
}
"""

CONNECTOR_STATUS_QUERY = """
query ConnectorStatus($stationId: String!, $connectorId: Int!) {
    StatusNotifications(
        where: {
            stationId: {_eq: $stationId},
            connectorId: {_eq: $connectorId}
        },
        order_by: {id: desc},
        limit: 1
    ) {
        connectorStatus
        connectorId
    }
}
"""
