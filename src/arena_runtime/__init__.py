"""Subscription-backed product-execution boundary for Agent Trading Arena.

R1 defines runtime vocabulary and planned module ownership only. Runtime code
may depend on the offline kernel in later deliverables; ``arena_kernel`` must
never depend on this package.
"""

from arena_runtime.module_map import CONCEPT_OWNERS, RUNTIME_MODULES
from arena_runtime.vocabulary import STABLE_TERMS

__all__ = [
    "CONCEPT_OWNERS",
    "RUNTIME_MODULES",
    "STABLE_TERMS",
]
