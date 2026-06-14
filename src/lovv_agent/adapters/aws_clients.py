"""AWS client factory placeholder.

Concrete boto3 client creation is intentionally deferred. Keeping this module
side-effect free prevents credential or network access during package import.
"""

from __future__ import annotations

ADAPTER_NAME = "AwsClientFactory"

RESPONSIBILITY = "Create AWS clients lazily from injected runtime config."

__all__ = ["ADAPTER_NAME", "RESPONSIBILITY"]
