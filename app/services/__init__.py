"""Application services: admission, the single Runner (with crash reconciliation) and job results.

Dependency rule: Interface (``app.api``) -> Services (here) -> Domains -> Core. Only the Runner
opens the Core ``Runtime``; the API never does.
"""
