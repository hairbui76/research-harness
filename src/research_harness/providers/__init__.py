"""Adapters that hide vendor APIs behind provider-neutral contracts.

Nothing above this package may name a vendor: application code asks for
capabilities and schemas, and this package decides which HTTP wire format
satisfies them.
"""

from __future__ import annotations
