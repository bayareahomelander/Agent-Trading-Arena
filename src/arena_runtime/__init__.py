"""Subscription-backed product-execution boundary for Agent Trading Arena.

R1 defines runtime vocabulary and planned module ownership only. Runtime code
may depend on the offline kernel in later deliverables; ``arena_kernel`` must
never depend on this package.
"""

from arena_runtime.audit import (
    AUDIT_EVENT_TYPES,
    AUDIT_SCHEMA_VERSION,
    NORMALIZED_EVENTS_PATH,
    PROVIDER_ARTIFACT_PREFIX,
    REDACTION_MARKER,
    AuditArchive,
    AuditArchiveError,
    AuditEvent,
    ProviderArtifactReference,
    audit_event_to_dict,
    dump_audit_event,
    parse_audit_event,
    redact_provider_bytes,
    validate_audit_environment,
)
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
    "AUDIT_EVENT_TYPES",
    "AUDIT_SCHEMA_VERSION",
    "NORMALIZED_EVENTS_PATH",
    "PROVIDER_ARTIFACT_PREFIX",
    "REDACTION_MARKER",
    "AuditArchive",
    "AuditArchiveError",
    "AuditEvent",
    "CAPABILITY_NAMES",
    "CONCEPT_OWNERS",
    "PreflightResult",
    "ProviderArtifactReference",
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
    "audit_event_to_dict",
    "dump_audit_event",
    "dump_runtime_registration",
    "parse_audit_event",
    "parse_runtime_registration",
    "redact_provider_bytes",
    "require_matching_identity",
    "runtime_registration_to_dict",
    "validate_audit_environment",
]
