"""数据质量反馈业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

import threading
from datetime import datetime
from typing import Any

from app.store import store

MODULE = "feedback"
REQUIRED_FIELDS = ["反馈编号", "数据产品", "反馈类型"]
# 登记时必须完整保留的业务字段，保证保存后详情能完整回显
ENTRY_FIELDS = ["反馈编号", "数据产品", "反馈类型", "反馈内容", "严重程度", "反馈人", "反馈时间"]
STATUS_ORDER = ["待处理", "处理中", "已解决", "已关闭"]
# 动作 -> (前置状态, 目标状态)：状态机只能沿 待处理→处理中→已解决→已关闭 单向推进
ACTION_RULES = {"开始处理": ("待处理", "处理中"), "标记解决": ("处理中", "已解决"), "关闭反馈": ("已解决", "已关闭")}
# 动作允许写入的处理类字段；反馈原始内容（严重程度、反馈时间、反馈人、反馈内容等）不允许被动作覆盖
ACTION_FIELDS = ["解决轨迹", "处理人"]
# 未解决口径：待处理、处理中；已解决、已关闭都视为已办结
UNRESOLVED_STATUSES = {"待处理", "处理中"}
# 系统字段不允许通过登记入参覆盖
SYSTEM_FIELDS = {"id", "status", "pending", "abnormal", "处理状态", "处理记录"}

# 动作是 读状态-校验-写状态 的复合操作，加锁保证并发关闭只落一次
_action_lock = threading.Lock()


class FeedbackService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("反馈编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        # 完整保留提交的业务字段，系统字段不允许入参覆盖
        entry.update({key: value for key, value in values.items() if key not in SYSTEM_FIELDS})
        for field in ENTRY_FIELDS:
            entry.setdefault(field, "")
        entry["status"] = STATUS_ORDER[0]
        entry["处理状态"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        entry.setdefault("解决轨迹", "")
        entry.setdefault("处理人", "")
        entry.setdefault("处理时间", "")
        entry["处理记录"] = []
        rows.append(entry)
        return entry, []

    def run_action(
        self,
        entry_id: int,
        action: str,
        values: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        values = values or {}
        with _action_lock:
            entry = store.find(MODULE, entry_id)
            if entry is None:
                return None, f"反馈记录 {entry_id} 不存在或已归档"
            if action not in ACTION_RULES:
                return None, f"动作「{action}」不属于数据质量反馈可执行范围"
            current = str(entry.get("status") or STATUS_ORDER[0])
            if current == STATUS_ORDER[-1]:
                return None, "反馈记录已关闭，关闭后不能重开"
            expected, target = ACTION_RULES[action]
            if current != expected:
                return None, f"反馈记录当前状态为「{current}」，「{action}」只能在「{expected}」状态下执行"
            if action == "标记解决" and not str(values.get("解决轨迹") or "").strip():
                return None, "标记解决前必须填写解决轨迹"
            entry["status"] = target
            entry["处理状态"] = target
            entry["pending"] = target in UNRESOLVED_STATUSES
            entry["abnormal"] = False
            for field in ACTION_FIELDS:
                value = values.get(field)
                if value is not None and str(value).strip():
                    entry[field] = value
            entry["处理时间"] = str(values.get("处理时间") or "").strip() or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            entry.setdefault("处理记录", []).append({
                "动作": action,
                "处理人": entry.get("处理人", ""),
                "解决轨迹": entry.get("解决轨迹", ""),
                "处理时间": entry["处理时间"],
                "结果状态": target,
            })
            return entry, f"反馈记录已{action}"

    def summary_for_product(self, *product_keys: str) -> dict[str, Any]:
        """数据产品定义读取用：某产品关联反馈的未解决数量与最新质量反馈处理结果。"""
        keys = {key for key in product_keys if key}
        rows = [row for row in store.rows(MODULE) if str(row.get("数据产品") or "") in keys]
        unresolved = sum(1 for row in rows if row.get("status") in UNRESOLVED_STATUSES)
        latest = max(rows, key=lambda row: int(row.get("id", 0)), default=None)
        latest_result = None
        if latest is not None:
            latest_result = {
                "反馈编号": latest.get("反馈编号", ""),
                "处理状态": latest.get("status", ""),
                "解决轨迹": latest.get("解决轨迹", ""),
                "处理人": latest.get("处理人", ""),
                "处理时间": latest.get("处理时间", ""),
            }
        return {"未解决数量": unresolved, "最新质量反馈处理结果": latest_result}
