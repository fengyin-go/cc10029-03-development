"""运行监控 分析看板服务：汇总指标、运行分析并生成模拟结果。

监控事件清单读取告警中心的告警关联处置数据包：时间范围、错误次数与处置主事件保持一致，
告警中心结论由此同步到运行监控，两个模块看到的是同一份成功版本。
"""
from __future__ import annotations

import random
from typing import Any

from app.services.alert_package import alert_package_service
from app.store import store

MODULE = "monitor"
REQUIRED_FIELDS = ["大盘编号", "关联任务", "采集速率"]
STATUS_ORDER = ["草稿", "待校验", "已启用", "已停用"]
ACTION_RULES = {"提交校验": "待校验", "启用配置": "已启用", "停用配置": "已停用"}
NEGATIVE_ACTIONS = ["停用配置"]


class MonitorService:
    def list_results(self) -> list[dict[str, Any]]:
        rows = store.rows(MODULE)
        results: list[dict] = []
        for row in rows:
            d = dict(row)
            d["指标值"] = round(random.uniform(0.65, 0.98), 3)
            d["对比基准"] = round(random.uniform(0.60, 0.92), 3)
            d["差异"] = round(d["指标值"] - d["对比基准"], 3)
            results.append(d)
        return results

    def run_analysis(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        count = int(params.get("样本范围", params.get("并行数量", "6")))
        results: list[dict] = []
        for i in range(count):
            results.append({
                "id": i + 1,
                "分组": f"分组{(i%3)+1}",
                "指标值": round(random.uniform(0.62, 1.02), 3),
                "对比基准": round(random.uniform(0.58, 0.95), 3),
                "差异": round(random.uniform(-0.2, 0.3), 3),
            })
        return results

    def list_alert_events(self, *, 监控对象: str | None = None) -> list[dict[str, Any]]:
        """读取告警关联处置数据包生成监控事件清单（告警中心结论同步入口）。"""
        return alert_package_service.monitor_events(监控对象=监控对象)

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)
