"""CollectorClient 错误路径单元测试：瞬时连接失败重试，非连接错误直抛。"""

import httpx
import pytest

import tools.collector_client as collector_client_module
from tools.collector_client import CollectorClient, CollectorError


@pytest.fixture(autouse=True)
def _zero_backoff(monkeypatch):
    """测试中去除退避等待，只验证重试次数与结果。"""
    monkeypatch.setattr(collector_client_module, "_CONNECT_RETRY_BACKOFF_S", 0)


def _client(handler) -> CollectorClient:
    return CollectorClient(
        base_url="http://collector.test", transport=httpx.MockTransport(handler)
    )


def test_connect_error_retried_then_success():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if len(calls) == 1:
            raise httpx.ConnectError(
                "[Errno 8] nodename nor servname provided, or not known",
                request=request,
            )
        return httpx.Response(200, json=[{"nav_date": "2026-09-18", "unit_nav": 1.0}])

    client = _client(handler)
    try:
        assert client.get_fund_nav("000001") == [{"nav_date": "2026-09-18", "unit_nav": 1.0}]
        assert len(calls) == 2
    finally:
        client.close()


def test_connect_error_exhausted_raises_collector_error():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        raise httpx.ConnectError("connect failed", request=request)

    client = _client(handler)
    try:
        with pytest.raises(CollectorError, match=r"collector /api/funds/000001/nav failed:"):
            client.get_fund_nav("000001")
        assert len(calls) == 3
    finally:
        client.close()


def test_non_connect_error_not_retried():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(500, json={"detail": "boom"})

    client = _client(handler)
    try:
        with pytest.raises(CollectorError, match="500 Internal Server Error"):
            client.get_fund_nav("000001")
        assert len(calls) == 1
    finally:
        client.close()
