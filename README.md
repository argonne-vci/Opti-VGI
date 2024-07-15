# Argonne Opti-VGI

### Opti-VGI: EV Smart Charging Scheduler Application

## Description

Opti-VGI is an EV smart charging management application designed to optimize electric vehicle charging based on power or pricing constraints. This application can integrate with any OCPP 2.X CSMS to accomplish ISO 15118 charge scheduling


## Proposed System Architecture

### Translation Layer
- An application that interfaces between the Charge Station Management System (CSMS) and the Charge Scheduling Management Algorithm (CSM)

### Modular Charge Scheduling Management (SCM) Application
- A modular framework that allows using different algorithms
