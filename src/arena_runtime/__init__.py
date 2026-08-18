"""Subscription-backed product-execution boundary for Agent Trading Arena.

R1 defines runtime vocabulary and planned module ownership only. Runtime code
may depend on the offline kernel in later deliverables; ``arena_kernel`` must
never depend on this package.
"""

from arena_runtime.module_map import CONCEPT_OWNERS, RUNTIME_MODULES
from arena_runtime.registration import (
    CAPABILITY_NAMES,
    SUBSCRIPTION_AUTHENTICATION,
    RuntimeCapabilities,
    RuntimeRegistration,
    dump_runtime_registration,
    parse_runtime_registration,
    runtime_registration_to_dict,
)
from arena_runtime.runner import (
    RUNNER_CONTRACT_VERSION,
    RUNNER_OUTCOMES,
    PreflightResult,
    Runner,
    RunnerContractError,
    RunnerRequest,
    RunnerResult,
    require_matching_identity,
)
from arena_runtime.vocabulary import STABLE_TERMS

__all__ = [
    "CAPABILITY_NAMES",
    "CONCEPT_OWNERS",
    "PreflightResult",
    "RUNNER_CONTRACT_VERSION",
    "RUNNER_OUTCOMES",
    "RUNTIME_MODULES",
    "RuntimeCapabilities",
    "RuntimeRegistration",
    "Runner",
    "RunnerContractError",
    "RunnerRequest",
    "RunnerResult",
    "STABLE_TERMS",
    "SUBSCRIPTION_AUTHENTICATION",
    "dump_runtime_registration",
    "parse_runtime_registration",
    "require_matching_identity",
    "runtime_registration_to_dict",
]
