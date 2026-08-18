"""Offline paper-exchange kernel for Agent Trading Arena.

D1 defines vocabulary and module boundaries only. Later deliverables
add types, schemas, and matching. This package must not talk to agent
products or live market-data vendors.
"""

from arena_kernel.module_map import CONCEPT_OWNERS, KERNEL_MODULES
from arena_kernel.vocabulary import ROUND_KINDS, STABLE_TERMS

__all__ = [
    "CONCEPT_OWNERS",
    "KERNEL_MODULES",
    "ROUND_KINDS",
    "STABLE_TERMS",
]
