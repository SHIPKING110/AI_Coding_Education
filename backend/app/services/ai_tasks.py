"""AI 出题异步任务管理（M4 增强，task-cancel-recover）：

- AI 生成耗时较长（真实 LLM 通常 20-60 秒），改为**提交立即返回 task_id**，后台线程执行
- 前端轮询 `GET /assignments/ai-tasks/{id}` 获取 状态/阶段/结果，期间可自由切换到其他页面
- 单 worker 串行执行；并发提交时后续任务显示「排队中」
- runner 可接收一个 `report(stage)` 回调，执行中随时上报阶段文案（前端实时可见）
- 内存存储（单进程 uvicorn），最多保留 TASK_LIMIT 个历史任务
- 取消与自恢复：pending 任务可取消（执行前检查取消标记直接落 cancelled）；
  running 任务取消会打标记并由下一次 report/完成时收敛（LLM 同步调用不可强杀）；
  长时间无心跳的 pending/running 任务在读取时自动标记为失败（stale 自恢复），
  前端轮询到 404（后端重启丢内存）时按“记录丢失”收敛，不会无限转圈
"""

import inspect
import threading
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

_TASK_LIMIT = 30
_POLL_STAGE = "AI 正在生成中…（通常需要 20-60 秒，请耐心等待）"
_QUEUE_STAGE = "排队中（等待前面的 AI 任务完成）"
_DONE_STAGES = {
    "class_parent_ppt": "已完成，可下载班级家长会 PPT",
}
_DEFAULT_DONE_STAGE = "已完成，可查看并加入作业"

# 无心跳超时：单任务 LLM 约 20-60 秒 + 单 worker 排队，15 分钟无进展视为僵死；
# 运行中一次性失败（超时/断网/429）自动重试一次后才落 failed（异常自恢复）
_STALE_SECONDS = 15 * 60
_RETRYABLE_MARKERS = (
    "timed out", "timeout", "temporarily", "try again", "connection",
    "connect", "network", "econn", "socket", "429", "rate limit",
    "overloaded", "unavailable", "bad gateway", "gateway timeout",
    "service unavailable", "internal error", "超", "重试",
)
_MAX_ATTEMPTS = 2

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ai-task")
_lock = threading.Lock()
_tasks: dict[str, dict[str, Any]] = {}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def _accepts_report(runner: Callable[..., Any]) -> bool:
    """runner 是否声明了可传入 report 回调的位置参数。"""
    try:
        sig = inspect.signature(runner)
    except (TypeError, ValueError):
        return False
    for p in sig.parameters.values():
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD):
            return True
    return False


def create_task(
    *,
    owner_id: str,
    kind: str,
    summary: str,
    runner: Callable[..., Any],
    dedup_key: str | None = None,
) -> dict[str, Any]:
    """创建任务并提交后台执行，立即返回任务记录（不含结果，结果完成后写入）。

    - owner_id: 提交人（用于隔离；admin/staff 可查看全部）
    - kind: 任务类型（generate/refine/class_parent_ppt…），决定完成态文案等
    - summary: 人类可读的任务描述（前端任务卡展示）
    - runner: 执行体，返回值写入 result，抛异常写入 error；
      可声明一个参数接收 report(stage) 回调，用于上报执行阶段
    - dedup_key: 去重键（同 owner+kind+dedup_key 仅允许一个 pending/running 任务，
      用于防重复提交；为 None 时不去重）
    """
    task: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "owner_id": owner_id,
        "kind": kind,
        "summary": summary,
        "status": "pending",
        "stage": _QUEUE_STAGE,
        "result": None,
        "error": None,
        "created_at": _now_iso(),
        "started_at": None,
        "finished_at": None,
        "cancel_requested": False,
        "attempts": 1,
        "heartbeat_at": _now_iso(),
    }
    if dedup_key is not None:
        task["dedup_key"] = dedup_key
    with _lock:
        _tasks[task["id"]] = task
        _trim()
    _executor.submit(_run, task["id"], runner, _accepts_report(runner))
    return dict(task)


def find_running_by_dedup(
    *, owner_id: str | None, kind: str, dedup_key: str
) -> dict[str, Any] | None:
    """查找同类型同去重键的进行中任务（pending/running），供提交时去重。

    owner_id=None 时跨提交人全局查找（班级 PPT 同班同周期全局仅允许一个在途任务，
    避免教师与管理员并发重复提交）；传入 owner_id 则仅查该提交人。
    """
    with _lock:
        for t in _tasks.values():
            if (
                (owner_id is None or t.get("owner_id") == owner_id)
                and t.get("kind") == kind
                and t.get("dedup_key") == dedup_key
                and t.get("status") in ("pending", "running")
            ):
                return dict(t)
    return None


def _is_retryable(exc: BaseException) -> bool:
    """一次性 LLM/网络失败是否值得自动重试一次（异常自恢复）。"""
    name = exc.__class__.__name__.lower()
    if any(k in name for k in ("timeout", "connection", "network", "ratelimit", "apiconnection", "apitimeout")):
        return True
    text = f"{exc}".lower()
    return any(m in text for m in _RETRYABLE_MARKERS)


def _finalize_failure(task_id: str, exc: BaseException) -> None:
    with _lock:
        task = _tasks.get(task_id)
        if task is None:
            return
        if task.get("cancel_requested"):
            task["status"] = "cancelled"
            task["stage"] = "任务已取消"
        else:
            task["status"] = "failed"
            task["stage"] = "生成失败"
            task["error"] = str(exc) or exc.__class__.__name__
        task["finished_at"] = _now_iso()


def _run(task_id: str, runner: Callable[..., Any], accepts_report: bool) -> None:
    with _lock:
        task = _tasks.get(task_id)
        if task is None:
            return
        if task.get("cancel_requested"):
            task["status"] = "cancelled"
            task["stage"] = "任务已取消"
            task["finished_at"] = _now_iso()
            return
        task["status"] = "running"
        task["stage"] = _POLL_STAGE
        task["started_at"] = _now_iso()
        task["heartbeat_at"] = _now_iso()

    def report(stage: str) -> None:
        with _lock:
            cur = _tasks.get(task_id)
            if cur is not None and cur["status"] == "running":
                cur["stage"] = stage
                cur["heartbeat_at"] = _now_iso()

    try:
        result = runner(report) if accepts_report else runner()
    except Exception as e:  # noqa: BLE001 —— 后台线程兜底，错误写入任务
        with _lock:
            task = _tasks.get(task_id)
            attempts = int((task or {}).get("attempts") or 1)
        # 一次性失败自动重试一次：回到排队尾，避免偶发超时/断网直接失败
        if attempts < _MAX_ATTEMPTS and _is_retryable(e) and not ((task or {}).get("cancel_requested")):
            with _lock:
                cur = _tasks.get(task_id)
                if cur is not None:
                    cur["attempts"] = attempts + 1
                    cur["status"] = "pending"
                    cur["stage"] = f"首次尝试遇到偶发错误（{str(e)[:24] or e.__class__.__name__}），正在自动重试…"
                    cur["heartbeat_at"] = _now_iso()
            _executor.submit(_run, task_id, runner, accepts_report)
            return
        _finalize_failure(task_id, e)
        return
    with _lock:
        task = _tasks.get(task_id)
        if task is None:
            return
        if task.get("cancel_requested"):
            task["status"] = "cancelled"
            task["stage"] = "任务已取消"
            task["finished_at"] = _now_iso()
            return
        task["status"] = "done"
        task["stage"] = _DONE_STAGES.get(task["kind"], _DEFAULT_DONE_STAGE)
        task["result"] = result
        task["finished_at"] = _now_iso()


def cancel_task(task_id: str, *, owner_id: str | None = None) -> dict[str, Any] | None:
    """请求取消任务：pending 直接落 cancelled；running 打标记由执行收敛。

    owner_id 非空时仅允许取消自己的任务（调用方已做 admin/staff 豁免判断时传 None）。
    返回取消后的任务快照；任务不存在返回 None；已终态返回原快照（不重复落库）。
    """
    with _lock:
        task = _tasks.get(task_id)
        if task is None:
            return None
        if owner_id is not None and task.get("owner_id") != owner_id:
            return dict(task)
        if task.get("status") in ("done", "failed", "cancelled"):
            return dict(task)
        task["cancel_requested"] = True
        if task.get("status") == "pending":
            task["status"] = "cancelled"
            task["stage"] = "任务已取消"
            task["finished_at"] = _now_iso()
        else:
            task["stage"] = "正在取消…（当前步骤完成后停止）"
            task["heartbeat_at"] = _now_iso()
        return dict(task)


def _maybe_mark_stale(task: dict[str, Any]) -> dict[str, Any]:
    """读取时自恢复：pending/running 长时间无心跳视为僵死，标记失败并给出可重试文案。"""
    if task.get("status") not in ("pending", "running"):
        return task
    heartbeat = _parse_iso(task.get("heartbeat_at") or task.get("started_at") or task.get("created_at"))
    if heartbeat is None:
        return task
    elapsed = (datetime.now(UTC) - heartbeat).total_seconds()
    if elapsed < _STALE_SECONDS:
        return task
    task["status"] = "failed"
    task["stage"] = "生成失败"
    task["error"] = "任务长时间无响应，已自动终止，请重新提交（15 分钟无进展自恢复）"
    task["finished_at"] = _now_iso()
    return task


def get_task(task_id: str) -> dict[str, Any] | None:
    with _lock:
        task = _tasks.get(task_id)
        if task is None:
            return None
        _maybe_mark_stale(task)
        return dict(task)


def list_tasks(owner_id: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    """最近任务（新在前）；owner_id=None 表示全部（admin/staff）。"""
    with _lock:
        for task in _tasks.values():
            _maybe_mark_stale(task)
        items = sorted(_tasks.values(), key=lambda t: t["created_at"], reverse=True)
        if owner_id is not None:
            items = [t for t in items if t["owner_id"] == owner_id]
        return [dict(t) for t in items[:limit]]


def _trim() -> None:
    if len(_tasks) <= _TASK_LIMIT:
        return
    by_created = sorted(_tasks.values(), key=lambda t: t["created_at"])
    for t in by_created[: len(_tasks) - _TASK_LIMIT]:
        _tasks.pop(t["id"], None)
