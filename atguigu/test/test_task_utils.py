import pytest
from atguigu.tool.task_utils import (
    get_task_status,
    update_task_status,
    TASK_STATUS_PROCESSING,
    TASK_STATUS_COMPLETED,
    TASK_STATUS_FAILED,
)
from atguigu.tool import task_utils


@pytest.fixture(autouse=True)
def cleanup_task_status():
    """每个测试前后清理全局任务状态，确保测试隔离性。"""
    original_status = task_utils._tasks_status.copy()
    yield
    task_utils._tasks_status.clear()
    task_utils._tasks_status.update(original_status)


class TestGetTaskStatus:
    """get_task_status 函数的单元测试"""

    def test_task_id_not_exists_returns_empty_string(self):
        """
        测试：当 task_id 不存在时，应返回空字符串。
        """
        result = get_task_status("non_existent_task_id")
        assert result == ""

    def test_task_id_with_none_returns_empty_string(self):
        """
        测试：当传入 None 作为 task_id 时，应返回空字符串。
        """
        result = get_task_status(None)
        assert result == ""

    def test_task_id_with_processing_status(self):
        """
        测试：当 task_id 存在且状态为 processing 时，应正确返回。
        """
        task_id = "test_task_001"
        update_task_status(task_id, TASK_STATUS_PROCESSING)

        result = get_task_status(task_id)
        assert result == TASK_STATUS_PROCESSING
        assert result == "processing"

    def test_task_id_with_completed_status(self):
        """
        测试：当 task_id 存在且状态为 completed 时，应正确返回。
        """
        task_id = "test_task_002"
        update_task_status(task_id, TASK_STATUS_COMPLETED)

        result = get_task_status(task_id)
        assert result == TASK_STATUS_COMPLETED
        assert result == "completed"

    def test_task_id_with_failed_status(self):
        """
        测试：当 task_id 存在且状态为 failed 时，应正确返回。
        """
        task_id = "test_task_003"
        update_task_status(task_id, TASK_STATUS_FAILED)

        result = get_task_status(task_id)
        assert result == TASK_STATUS_FAILED
        assert result == "failed"

    def test_task_id_with_custom_status(self):
        """
        测试：当使用自定义状态字符串时，应正确返回。
        """
        task_id = "test_task_004"
        custom_status = "custom_status_value"
        update_task_status(task_id, custom_status)

        result = get_task_status(task_id)
        assert result == custom_status

    def test_empty_string_task_id(self):
        """
        测试：当 task_id 为空字符串时，应返回空字符串。
        """
        result = get_task_status("")
        assert result == ""

    def test_multiple_tasks_independent(self):
        """
        测试：多个不同任务的状态应相互独立。
        """
        task_id_1 = "task_1"
        task_id_2 = "task_2"
        task_id_3 = "task_3"

        update_task_status(task_id_1, TASK_STATUS_PROCESSING)
        update_task_status(task_id_2, TASK_STATUS_COMPLETED)
        update_task_status(task_id_3, TASK_STATUS_FAILED)

        assert get_task_status(task_id_1) == TASK_STATUS_PROCESSING
        assert get_task_status(task_id_2) == TASK_STATUS_COMPLETED
        assert get_task_status(task_id_3) == TASK_STATUS_FAILED

    def test_same_task_id_status_overwrite(self):
        """
        测试：同一任务 ID 的状态可以被覆盖更新。
        """
        task_id = "test_task_overwrite"

        update_task_status(task_id, TASK_STATUS_PROCESSING)
        assert get_task_status(task_id) == TASK_STATUS_PROCESSING

        update_task_status(task_id, TASK_STATUS_COMPLETED)
        assert get_task_status(task_id) == TASK_STATUS_COMPLETED

        update_task_status(task_id, TASK_STATUS_FAILED)
        assert get_task_status(task_id) == TASK_STATUS_FAILED

    def test_task_status_update_and_get_cycle(self):
        """
        测试：完整的更新和获取状态循环。
        """
        task_id = "test_task_cycle"

        # 初始状态应为空
        initial_status = get_task_status(task_id)
        assert initial_status == ""

        # 更新为 processing
        update_task_status(task_id, TASK_STATUS_PROCESSING)
        processing_status = get_task_status(task_id)
        assert processing_status == "processing"

        # 更新为 completed
        update_task_status(task_id, TASK_STATUS_COMPLETED)
        completed_status = get_task_status(task_id)
        assert completed_status == "completed"
