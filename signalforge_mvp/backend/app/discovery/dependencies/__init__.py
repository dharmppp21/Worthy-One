"""Service dependency detection subpackage."""

from app.discovery.dependencies.models import DependencyGraph, ServiceDependency
from app.discovery.dependencies.network_scanner import NetworkConnectionScanner
from app.discovery.dependencies.registry import DependencyRegistry
from app.discovery.dependencies.traffic_analyzer import TrafficAnalyzer
from app.discovery.dependencies.trace_analyzer import TraceAnalyzer

__all__ = [
    "DependencyGraph",
    "DependencyRegistry",
    "NetworkConnectionScanner",
    "ServiceDependency",
    "TrafficAnalyzer",
    "TraceAnalyzer",
]
