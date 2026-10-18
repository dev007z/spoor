"""Resolve the adapter for a chain from settings.SPOOR_CHAIN_ADAPTERS.

Each entry maps a chain key to {"class": dotted path, "options": constructor kwargs}.
A deployment adds or swaps providers by changing settings, not code.
"""

from django.conf import settings
from django.utils.module_loading import import_string

from spoor.modules.chains.adapters.base import AdapterError


class AdapterNotConfiguredError(AdapterError):
    pass


def get_adapter_config(chain):
    config = settings.SPOOR_CHAIN_ADAPTERS.get(chain.key)
    if config is None:
        raise AdapterNotConfiguredError(f"No adapter configured for chain {chain.key!r}")
    return import_string(config["class"]), config.get("options", {})


def get_adapter(chain, **overrides):
    adapter_class, options = get_adapter_config(chain)
    return adapter_class(chain, **{**options, **overrides})
