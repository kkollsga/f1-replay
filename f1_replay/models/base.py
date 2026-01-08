"""
Base classes for F1 data models.

Provides F1DataMixin with dict-like access for all dataclasses.
"""

from dataclasses import fields
from typing import Dict, List, Any


class F1DataMixin:
    """
    Mixin providing dict-like access for F1 dataclasses.

    All F1 data models inherit this for convenient .keys(), .values(), etc.
    """

    def keys(self) -> List[str]:
        """Return list of field names."""
        return [f.name for f in fields(self)]

    def values(self) -> List[Any]:
        """Return list of field values."""
        return [getattr(self, f.name) for f in fields(self)]

    def items(self) -> List[tuple]:
        """Return list of (field_name, value) tuples."""
        return [(f.name, getattr(self, f.name)) for f in fields(self)]

    def get(self, key: str, default: Any = None) -> Any:
        """Get field value by name with optional default."""
        return getattr(self, key, default)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {f.name: getattr(self, f.name) for f in fields(self)}

    def __getitem__(self, key: str) -> Any:
        """Allow dict-style access: obj['field']."""
        if hasattr(self, key):
            return getattr(self, key)
        raise KeyError(key)

    def __contains__(self, key: str) -> bool:
        """Support 'in' operator: 'field' in obj."""
        return key in self.keys()
