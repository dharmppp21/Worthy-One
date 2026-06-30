"""Mock helpers for Docker integration tests.

Provides factory functions to create realistic mock Docker containers
and psutil network connections so integration tests can run without a
real Docker daemon.
"""
from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import MagicMock


class FakeContainer:
    """Lightweight fake container that quacks like a docker.Container."""

    def __init__(
        self,
        name: str,
        image: str,
        short_id: str,
        attrs: Dict[str, Any],
    ) -> None:
        self.name = name
        self.short_id = short_id
        self.id = short_id
        self.attrs = attrs
        self.status = attrs.get("State", {}).get("Status", "running")

        # Build image mock with tags/id
        img_mock = MagicMock()
        img_mock.tags = [image]
        img_mock.id = image
        self.image = img_mock

        # Labels from Config/Labels, or empty
        self.labels = attrs.get("Config", {}).get("Labels", {})

    def reload(self) -> None:
        pass

    def __repr__(self) -> str:
        return f"FakeContainer({self.name!r})"


def make_nginx_container() -> FakeContainer:
    """Return a fake nginx load-balancer container."""
    return FakeContainer(
        name="test-nginx-1",
        image="nginx:alpine",
        short_id="nginx1234",
        attrs={
            "Name": "/test-nginx-1",
            "Config": {
                "Image": "nginx:alpine",
                "Labels": {
                    "com.docker.compose.service": "nginx",
                },
            },
            "NetworkSettings": {
                "IPAddress": "172.18.0.2",
                "Ports": {
                    "80/tcp": [{"HostIp": "172.18.0.2", "HostPort": "80"}],
                },
                "Networks": {
                    "test-network": {
                        "IPAddress": "172.18.0.2",
                        "Aliases": ["nginx", "test-nginx-1"],
                    }
                },
            },
            "State": {"Running": True, "Status": "running", "Pid": 999},
        },
    )


def make_postgres_container() -> FakeContainer:
    """Return a fake postgres database container."""
    return FakeContainer(
        name="test-postgres-1",
        image="postgres:16-alpine",
        short_id="pg5678",
        attrs={
            "Name": "/test-postgres-1",
            "Config": {
                "Image": "postgres:16-alpine",
                "Labels": {
                    "com.docker.compose.service": "postgres",
                },
            },
            "NetworkSettings": {
                "IPAddress": "172.18.0.3",
                "Ports": {
                    "5432/tcp": [{"HostIp": "172.18.0.3", "HostPort": "5432"}],
                },
                "Networks": {
                    "test-network": {
                        "IPAddress": "172.18.0.3",
                        "Aliases": ["postgres", "test-postgres-1"],
                    }
                },
            },
            "State": {"Running": True, "Status": "running", "Pid": 2001},
        },
    )


def make_redis_container() -> FakeContainer:
    """Return a fake redis cache container."""
    return FakeContainer(
        name="test-redis-1",
        image="redis:7-alpine",
        short_id="redis90ab",
        attrs={
            "Name": "/test-redis-1",
            "Config": {
                "Image": "redis:7-alpine",
                "Labels": {
                    "com.docker.compose.service": "redis",
                },
            },
            "NetworkSettings": {
                "IPAddress": "172.18.0.4",
                "Ports": {
                    "6379/tcp": [{"HostIp": "172.18.0.4", "HostPort": "6379"}],
                },
                "Networks": {
                    "test-network": {
                        "IPAddress": "172.18.0.4",
                        "Aliases": ["redis", "test-redis-1"],
                    }
                },
            },
            "State": {"Running": True, "Status": "running", "Pid": 2002},
        },
    )


def make_python_api_container() -> FakeContainer:
    """Return a fake Python Flask API container."""
    return FakeContainer(
        name="test-python-api-1",
        image="python:3.12-slim",
        short_id="pyapi1def",
        attrs={
            "Name": "/test-python-api-1",
            "Config": {
                "Image": "python:3.12-slim",
                "Labels": {
                    "com.docker.compose.service": "python-api",
                    "app.kubernetes.io/name": "python-api",
                },
            },
            "NetworkSettings": {
                "IPAddress": "172.18.0.5",
                "Ports": {
                    "5000/tcp": [{"HostIp": "172.18.0.5", "HostPort": "5000"}],
                },
                "Networks": {
                    "test-network": {
                        "IPAddress": "172.18.0.5",
                        "Aliases": ["python-api", "test-python-api-1"],
                    }
                },
            },
            "State": {"Running": True, "Status": "running", "Pid": 1001},
        },
    )


def make_nodejs_api_container() -> FakeContainer:
    """Return a fake Node.js Express API container."""
    return FakeContainer(
        name="test-nodejs-api-1",
        image="node:20-alpine",
        short_id="node2a3b4c",
        attrs={
            "Name": "/test-nodejs-api-1",
            "Config": {
                "Image": "node:20-alpine",
                "Labels": {
                    "com.docker.compose.service": "nodejs-api",
                    "app.kubernetes.io/name": "nodejs-api",
                },
            },
            "NetworkSettings": {
                "IPAddress": "172.18.0.6",
                "Ports": {
                    "3000/tcp": [{"HostIp": "172.18.0.6", "HostPort": "3000"}],
                },
                "Networks": {
                    "test-network": {
                        "IPAddress": "172.18.0.6",
                        "Aliases": ["nodejs-api", "test-nodejs-api-1"],
                    }
                },
            },
            "State": {"Running": True, "Status": "running", "Pid": 1002},
        },
    )


def make_all_containers() -> list[FakeContainer]:
    """Return the full set of 5 fake containers."""
    return [
        make_nginx_container(),
        make_postgres_container(),
        make_redis_container(),
        make_python_api_container(),
        make_nodejs_api_container(),
    ]


# ------------------------------------------------------------------
# psutil connection mocks
# ------------------------------------------------------------------

class FakeConnection:
    """Lightweight fake that mimics a psutil _sconn namedtuple."""

    class _Raddr:
        def __init__(self, ip: str, port: int) -> None:
            self.ip = ip
            self.port = port

    def __init__(
        self,
        fd: int,
        family: int,
        type_: int,
        laddr,
        raddr,
        status: str,
        pid: int,
    ) -> None:
        self.fd = fd
        self.family = family
        self.type = type_
        self.laddr = laddr
        self.raddr = self._Raddr(raddr[0], raddr[1]) if raddr else None
        self.status = status
        self.pid = pid


def make_psutil_connections(
    python_api_pid: int = 1001,
    nodejs_api_pid: int = 1002,
    postgres_ip: str = "172.18.0.3",
    redis_ip: str = "172.18.0.4",
) -> list[FakeConnection]:
    """Return fake psutil connections that simulate the Python and Node APIs
    talking to Postgres and Redis."""
    from socket import AF_INET, SOCK_STREAM

    return [
        # Python API -> Postgres:5432
        FakeConnection(
            fd=-1,
            family=AF_INET,
            type_=SOCK_STREAM,
            laddr=("172.18.0.5", 5000),
            raddr=(postgres_ip, 5432),
            status="ESTABLISHED",
            pid=python_api_pid,
        ),
        # Python API -> Redis:6379
        FakeConnection(
            fd=-1,
            family=AF_INET,
            type_=SOCK_STREAM,
            laddr=("172.18.0.5", 5000),
            raddr=(redis_ip, 6379),
            status="ESTABLISHED",
            pid=python_api_pid,
        ),
        # Node.js API -> Postgres:5432
        FakeConnection(
            fd=-1,
            family=AF_INET,
            type_=SOCK_STREAM,
            laddr=("172.18.0.6", 3000),
            raddr=(postgres_ip, 5432),
            status="ESTABLISHED",
            pid=nodejs_api_pid,
        ),
        # Node.js API -> Redis:6379
        FakeConnection(
            fd=-1,
            family=AF_INET,
            type_=SOCK_STREAM,
            laddr=("172.18.0.6", 3000),
            raddr=(redis_ip, 6379),
            status="ESTABLISHED",
            pid=nodejs_api_pid,
        ),
        # Nginx -> Python API:5000 (reverse proxy)
        FakeConnection(
            fd=-1,
            family=AF_INET,
            type_=SOCK_STREAM,
            laddr=("172.18.0.2", 80),
            raddr=("172.18.0.5", 5000),
            status="ESTABLISHED",
            pid=999,
        ),
        # Nginx -> Node.js API:3000 (reverse proxy)
        FakeConnection(
            fd=-1,
            family=AF_INET,
            type_=SOCK_STREAM,
            laddr=("172.18.0.2", 80),
            raddr=("172.18.0.6", 3000),
            status="ESTABLISHED",
            pid=999,
        ),
    ]


# ------------------------------------------------------------------
# Docker client mock builder
# ------------------------------------------------------------------

def build_mock_docker_client(containers: list[FakeContainer]) -> MagicMock:
    """Return a MagicMock that behaves like docker.DockerClient."""
    client = MagicMock()
    client.containers.list.return_value = containers
    return client
