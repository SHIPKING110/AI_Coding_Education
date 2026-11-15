"""全局测试隔离：默认关闭 usage_meter，避免测试调用把账本写进开发/生产库。

`test_usage_billing.py` 的 `meter` fixture 会显式把 `enabled` 改回 True，并在测试库
上运行；其余用例（视觉/评测/模型连通等）即使触发真实下游调用，也只影响测试进程。
"""

import pytest


@pytest.fixture(autouse=True)
def _disable_usage_meter(monkeypatch):
    from app.services import usage_meter

    monkeypatch.setattr(usage_meter, "enabled", lambda: False)
    yield
