"""Abstract base class for dependency analyzers."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from app.discovery.dependencies.models import ServiceDependency


class BaseDependencyAnalyzer(ABC):
    """Abstract base class for all dependency analyzers.

    Concrete implementations must provide an ``analyze`` method that returns
    a list of ``ServiceDependency`` objects discovered by that analyzer.
    """

    @abstractmethod
    async def analyze(self) -> List[ServiceDependency]:
        """Run the analyzer and return discovered dependencies.

        Returns:
            List of ServiceDependency objects. Empty list if the analyzer
            is disabled or no dependencies were found.
        """
        ...

    def health_check(self) -> bool:
        """Return whether the analyzer is healthy and can run.

        Default implementation returns True. Subclasses may override to
        check external dependencies (e.g., Prometheus, trace backend).
        """
        return True
