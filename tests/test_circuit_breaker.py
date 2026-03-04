import pytest
import time
from app.utils.circuit_breaker import CircuitBreaker, CircuitState

def test_circuit_breaker():
    cb = CircuitBreaker("test", failure_threshold=2, recovery_timeout=1)
    call_count = 0
    def failing():
        nonlocal call_count
        call_count += 1
        raise Exception("fail")
    with pytest.raises(Exception):
        cb.call(failing)
    assert cb.state == CircuitState.CLOSED
    with pytest.raises(Exception):
        cb.call(failing)
    assert cb.state == CircuitState.OPEN
    with pytest.raises(Exception, match="OPEN"):
        cb.call(failing)
    assert call_count == 2
    time.sleep(1.1)
    with pytest.raises(Exception):
        cb.call(failing)
    assert cb.state == CircuitState.OPEN
    assert call_count == 3
