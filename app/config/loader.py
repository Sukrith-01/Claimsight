"""
Loads and validates per-tenant configuration from configs/*.yaml.

This is the actual multi-tenant mechanism the whole project is built
around: one codebase, N tenants, each with their own accepted document
types, review threshold, and field labels - driven entirely by a YAML
file, not a branch or a forked repo. Adding a new client should mean
"write a new YAML file," never "modify code that another client's
traffic also runs through."
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from app.config.schemas import ClientConfig

CONFIG_DIR = Path("configs")

# In-process cache: configs are read from disk once, not on every request.
# A real production version would need a way to bust this (e.g. on a
# config-reload endpoint or file-watch), deliberately left out for now -
# not needed until there's an actual deployed service where configs
# change without a redeploy. Adding that before it's needed is exactly
# the kind of premature complexity worth resisting.
_cache: dict[str, ClientConfig] = {}


class TenantNotFoundError(Exception):
    """Raised when a request references a tenant_id with no matching config file."""
    pass


class InvalidClientConfigError(Exception):
    """Raised when a tenant's config file exists but fails schema validation."""
    pass


def _config_path(tenant_id: str) -> Path:
    return CONFIG_DIR / f"client_{tenant_id}.yaml"


def load_client_config(tenant_id: str, use_cache: bool = True) -> ClientConfig:
    """
    Load and validate the config for one tenant. Raises TenantNotFoundError
    if no config file exists for that tenant_id, or InvalidClientConfigError
    if the file exists but doesn't match the ClientConfig schema.
    """
    if use_cache and tenant_id in _cache:
        return _cache[tenant_id]

    path = _config_path(tenant_id)
    if not path.exists():
        raise TenantNotFoundError(
            f"No configuration found for tenant '{tenant_id}' (expected {path})"
        )

    with open(path) as f:
        raw = yaml.safe_load(f)

    try:
        config = ClientConfig.model_validate(raw)
    except ValidationError as e:
        raise InvalidClientConfigError(
            f"Config for tenant '{tenant_id}' failed validation: {e}"
        )

    if config.tenant_id != tenant_id:
        raise InvalidClientConfigError(
            f"Config file {path} has tenant_id='{config.tenant_id}', "
            f"but was loaded as '{tenant_id}' - filename and internal "
            f"tenant_id must match to avoid silently loading the wrong client's config."
        )

    _cache[tenant_id] = config
    return config


def list_available_tenants() -> list[str]:
    """Scan configs/ for client_*.yaml files and return their tenant IDs."""
    if not CONFIG_DIR.exists():
        return []
    return sorted(
        p.stem.removeprefix("client_")
        for p in CONFIG_DIR.glob("client_*.yaml")
    )
