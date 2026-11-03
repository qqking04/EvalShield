"""ES8-BUG-013 外部联调用例注册：ext 标记 + 目标地址。不进主 CI。"""
import pytest

TARGET = "http://localhost:8000"


def pytest_configure(config):
    config.addinivalue_line("markers", "ext: 外部联调环境用例（Keycloak/支付宝沙箱，不进主 CI）")


@pytest.mark.ext
def test_smoke_health():
    """联调冒烟：栈起服后 /api/health 应 200。真实 SSO/支付用例（M2-E*/M10-E*）接通后在此扩展。"""
    import httpx

    r = httpx.get(f"{TARGET}/api/health", timeout=5)
    assert r.status_code == 200
