# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | Yes       |

## Reporting a vulnerability

Please **do not** open a public issue for security problems.

Email **rush0100@users.noreply.github.com** with:

- a description of the issue
- steps to reproduce (without proprietary TI binaries)
- impact assessment if known

You should receive an acknowledgment within a few business days. We will
coordinate a fix and disclosure timeline.

## Scope notes

This project talks to USB evaluation hardware. Treat any device that appears on
USB as untrusted input; report crashes or privilege issues in the host Python
stack here. Issues in TI firmware or the PDK should be reported to Texas
Instruments through their support channels.
