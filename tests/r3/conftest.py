"""Shared R3 registration fixture."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def valid_registration() -> dict[str, Any]:
    return deepcopy(
        {
            "schema_version": "1",
            "product_id": "product-a",
            "provider_id": "provider-a",
            "adapter_id": "adapter-a",
            "subscription_tier": "individual-usd-20",
            "authentication_method": "subscription",
            "exact_model": "registered-model-a",
            "reasoning_mode": "registered-stable-mode",
            "automatic_routing": False,
            "expected_cli_version": "1.2.3",
            "replica_ids": ["product-a-1", "product-a-2"],
            "capabilities": {
                "web_research": True,
                "shell_execution": True,
                "persistent_workspace": True,
                "resumable_sessions": True,
                "native_subagents": True,
            },
            "provider_documentation_url": "https://docs.example.test/product-cli",
            "provider_documentation_retrieved_on": "2026-08-17",
        }
    )
