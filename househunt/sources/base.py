"""Common interface for listing sources."""

from __future__ import annotations

from abc import ABC, abstractmethod

from househunt.models import Listing, SearchCriteria


class ListingSource(ABC):
    name: str

    def __init__(self, mock: bool = False):
        self.mock = mock

    def search(self, criteria: SearchCriteria) -> list[Listing]:
        if self.mock:
            return self.mock_results(criteria)
        return self.fetch(criteria)

    @abstractmethod
    def fetch(self, criteria: SearchCriteria) -> list[Listing]:
        """Hit the real site and return normalized listings."""

    @abstractmethod
    def mock_results(self, criteria: SearchCriteria) -> list[Listing]:
        """Canned listings so the pipeline can run end-to-end offline."""
