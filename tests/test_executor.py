import sys
import time
import pytest
sys.path.insert(0, '.')
from app.core.executor import TaskExecutor, Task, TaskStatus

def test_task_executor_parallel():
    executor = TaskExecutor(max_workers=2)
    results = []
    def slow_task(n):
        time.sleep(0.5)
        return n * 2
    task_ids = []
    for i in range(4):
        task = Task(id=f"task_{i}", name=f"Task {i}", func=slow_task, args=(i,))
        task_ids.append(executor.submit(task))
    start = time.time()
    for tid in task_ids:
        executor.get_task_result(tid)
    duration = time.time() - start
    assert duration < 1.5  # 2 workers * 2 lots = ~1s
    assert duration > 0.8
    executor.shutdown()

def test_dependencies():
    executor = TaskExecutor(max_workers=2)
    def task_a():
        time.sleep(0.2)
        return "A"
    def task_b(a_result):
        return f"B based on {a_result}"
    a = Task(id="a", name="A", func=task_a, args=())
    b = Task(id="b", name="B", func=task_b, args=(), dependencies=["a"])
    a_id = executor.submit(a)
    b_id = executor.submit(b)
    b_result = executor.get_task_result(b_id)
    assert "A" in b_result
    executor.shutdown()

def test_persistence(tmp_path):
    persist = tmp_path / "tasks.pkl"
    executor = TaskExecutor(max_workers=1, persist_path=persist)
    def dummy():
        return 42
    task = Task(id="test", name="test", func=dummy, args=())
    executor.submit(task)
    time.sleep(0.5)
    executor.shutdown()
    executor2 = TaskExecutor(max_workers=1, persist_path=persist)
    assert "test" in executor2.tasks
    assert executor2.tasks["test"].status == TaskStatus.COMPLETED
    executor2.shutdown()
