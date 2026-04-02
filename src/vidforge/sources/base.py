"""Data source base class."""

from abc import ABC
from abc import abstractmethod

from vidforge.models import Item


class Source(ABC):
    """Base class for data sources. Each source produces a list of Items."""

    @abstractmethod
    def fetch(self) -> list[Item]:
        """Fetch data from this source and return normalized Items."""
        ...

    @abstractmethod
    def preview_url(self, item: Item) -> str | None:
        """Return a preview URL for an item (e.g., image URL), or None."""
        ...
