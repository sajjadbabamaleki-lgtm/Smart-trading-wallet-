"""Platform services.

Each package is a bounded module inside the modular monolith (ADR-004).
Services depend on `libs`, never on each other's internals.
"""
