# -*- coding: utf-8 -*-
"""The AI system the gateway guards, as opposed to the models that judge for it.

One adapter, one endpoint, one POST. See `client.py` for why this is deliberately
not the judge provider chain.
"""
from .client import (  # noqa: F401
    ENV_API_KEY, ENV_BASE_URL, ENV_MAX_TOKENS, ENV_MODEL, ENV_PROBE_TIMEOUT,
    ENV_TIMEOUT, EndpointProbe, TargetClient, TargetCompletion, TargetConfig,
    TargetError, config_from_env, from_env, probe_endpoint, probe_timeout_from_env,
)

__all__ = [
    "ENV_API_KEY", "ENV_BASE_URL", "ENV_MAX_TOKENS", "ENV_MODEL",
    "ENV_PROBE_TIMEOUT", "ENV_TIMEOUT", "EndpointProbe", "TargetClient",
    "TargetCompletion", "TargetConfig", "TargetError", "config_from_env",
    "from_env", "probe_endpoint", "probe_timeout_from_env",
]
