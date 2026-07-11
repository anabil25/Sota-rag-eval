"""Web UI — primary interface for Retrieve.

FastAPI app wrapping the same core modules the CLI uses.
No logic duplication — all routes call the same Python functions.
"""

from retrieve.web.app import create_app

__all__ = ["create_app"]
