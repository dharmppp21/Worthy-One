"""
Abstract base class for service discovery providers.
"""
from abc import ABC, abstractmethod
from typing import List

from .models import DiscoveredService


class ServiceDiscoveryProvider(ABC):
    """
    Abstract base class for service discovery providers.

    Subclasses must implement:
      - discover(): scan the environment and return a list of DiscoveredService objects.
      - health_check(): verify that the provider can reach its target
        (e.g. the Docker daemon is running, the Kubernetes API is accessible, etc.).
    """

    @abstractmethod
    async def discover(self) -> List[DiscoveredService]:
        """
        Discover available services in the target environment.

        Returns:
            A list of DiscoveredService instances found by this provider.
        """
        ...  # pragma: no cover

    @abstractmethod
    async def health_check(self) -> bool:
        """
        Verify the provider can reach its target.

        Returns:
            True if the provider is healthy and able to perform discovery,
            False otherwise.
        """
        ...  # pragma: no cover
