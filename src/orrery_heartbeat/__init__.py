"""Shared runtime support for Orrery release binaries."""

from __future__ import annotations

import os
import ssl

import certifi

__version__ = "0.4.0"


def _ssl_context() -> ssl.SSLContext:
    """Use bundled roots unless the operator supplied a custom trust store."""
    if os.environ.get("SSL_CERT_FILE") or os.environ.get("SSL_CERT_DIR"):
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())
