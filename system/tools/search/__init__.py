"""
Search provider abstraction for AI Lab.

Odysseus search modules used as provider-abstraction reference only;
no Odysseus runtime or search code was copied.
"""

from .core import search, SearchResult
from .providers import DuckDuckGoProvider, SearXNGProvider

__all__ = ["search", "SearchResult", "DuckDuckGoProvider", "SearXNGProvider"]
