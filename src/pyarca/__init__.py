"""Framework-agnostic Python client for ARCA (ex AFIP) electronic invoicing."""

from importlib.metadata import version

__version__: str = version("pyarca")

__all__ = ["__version__"]
