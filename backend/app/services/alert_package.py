"""告警关联处置数据包服务。

把同一采集批次、同一监控对象下重复触发的告警规则归并成可处置的事件集合：

- 处置包与监控事件快照必须一起写入（原子提交），未关联到告警事件的规则不能进入处置包；
- 同一监控对象连续触发相同告警只保留一个处置主事件，后续触发只追加事件明细，不重复建包；
- 关闭事件与恢复事件命中同一主事件且先后冲突时，只输出一份带最终处置状态的关联包；
- 并发或连续两次提交相同的处置包时只保留一个成功版本，运行监控始终读取该版本。
"""
from __future__ import annotations

import json
import threading
from datetime import datetime
from typing import Any

from app.store import store

MODULE = "alert"
PACKAGE_MODULE = "alert_package"

# 规则命中的事件类型；触发类只追加明细，关闭/恢复类决定最终处置状态。
EVENT_TRIGGER = "触发"
EVENT_CLOSE = "关闭"
EVENT_RECOVER = "恢复"
LIFECYCLE_EVENTS = (EVENT_CLOSE, EVENT_RECOVER)
EVENT_TYPES = (EVENT_TRIGGER, EVENT_CLOSE, EVENT_RECOVER)

# 主事件与处置包的处置状态。
STATE_PROCESSING = "处置中"
STATE_CLOSED = "已关闭"
STATE_RECOVERED = "已恢复"

PACKAGE_REQUIRED_FIELDS = ["采集批次", "监控对象"]
HIT_REQUIRED_FIELDS = ["规则编号", "监控对象"]
SNAPSHOT_REQUIRED_FIELDS = ["事件时间范围", "错误次数", "监控对象", "采集批次"]

# 既有调用契约里的错误码：沿用 ok/message 结构，冲突类补充稳定 code，便于调用方分支处理。
CODE_UNASSOCIATED_RULE = "RULE_NOT_ASSOCIATED"
CODE_SNAPSHOT_MISSING = "SNAPSHOT_REQUIRED"
CODE_MISSING_FIELD = "MISSING_FIELD"
CODE_PACKAGE_CONFLICT = "PACKAGE_VERSION_CONFLICT"


class PackageConflictError(Exception):
    """处置包版本冲突：并发/连续重复提交时只保留先成功的版本。"""

    def __init__(self, message: str, package: dict[str, Any]) -> None:
        super().__init__(message)
        self.code = CODE_PACKAGE_CONFLICT
        self.package = package


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _fingerprint(payload: dict[str, Any]) -> str:
    """对归一化后的提交内容计算稳定指纹，用于识别完全相同的重复提交。"""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class AlertPackageService:
    def __init__(self) -> None:
        # 提交、归并、版本流转都在同一把锁内完成，保证并发提交只有一个成功版本。
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ 查询
    def list_packages(
        self,
        *,
        filters: dict[str, str] | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = [dict(row) for row in store.rows(PACKAGE_MODULE)]
        for field, expected in (filters or {}).items():
            rows = [row for row in rows if expected.casefold() in str(row.get(field, "")).casefold()]
        rows.sort(key=lambda row: (-_int(row.get("id")), str(row.get("采集批次", ""))))
        total = len(rows)
        start = (page - 1) * size
        return rows[start:start + size], total

    def get_package(self, package_id: int) -> dict[str, Any] | None:
        row = store.find(PACKAGE_MODULE, package_id)
        return dict(row) if row else None

    def dashboard(self) -> dict[str, Any]:
        """告警中心结果页看板：按最终处置状态分组展示处置包。"""
        rows = store.rows(PACKAGE_MODULE)
        groups: dict[str, list[dict[str, Any]]] = {
            STATE_PROCESSING: [], STATE_CLOSED: [], STATE_RECOVERED: [],
        }
        for row in rows:
            groups.setdefault(str(row.get("最终处置状态", STATE_PROCESSING)), []).append(dict(row))
        cards = [
            {"label": "处置包总数", "value": len(rows)},
            {"label": "处置中主事件", "value": sum(
                _int(row.get("主事件数")) for row in rows if row.get("最终处置状态") == STATE_PROCESSING)},
            {"label": "已关闭主事件", "value": sum(
                _int(row.get("已关闭数")) for row in rows)},
            {"label": "已恢复主事件", "value": sum(
                _int(row.get("已恢复数")) for row in rows)},
        ]
        return {
            "cards": cards,
            "groups": [
                {"状态": state, "items": groups.get(state, [])}
                for state in (STATE_PROCESSING, STATE_CLOSED, STATE_RECOVERED)
            ],
        }

    def monitor_events(self, *, 监控对象: str | None = None) -> list[dict[str, Any]]:
        """运行监控读取处置包生成监控事件清单。

        事件的时间范围与错误次数必须与处置主事件一致，这里直接取主事件上的归并结果，
        保证告警中心与运行监控看到的是同一份成功版本。
        """
        events: list[dict[str, Any]] = []
        for package in store.rows(PACKAGE_MODULE):
            if 监控对象 and 监控对象.casefold() not in str(package.get("监控对象", "")).casefold():
                continue
            for main in package.get("处置主事件", []):
                events.append({
                    "事件编号": main["主事件编号"],
                    "采集批次": package.get("采集批次"),
                    "监控对象": package.get("监控对象"),
                    "规则编号": main.get("规则编号"),
                    "告警条件": main.get("告警条件"),
                    "时间范围": main.get("时间范围"),
                    "错误次数": main.get("错误次数"),
                    "命中次数": main.get("命中次数"),
                    "处置状态": main.get("处置状态"),
                    "处置包编号": package.get("处置包编号"),
                    "版本": package.get("版本"),
                })
        events.sort(key=lambda item: (str(item["采集批次"]), str(item["事件编号"])))
        return events

    # ------------------------------------------------------------------ 提交
    def submit_package(self, payload: dict[str, Any]) -> tuple[dict[str, Any] | None, str, str | None]:
        """提交一份告警关联处置数据包。

        返回 (处置包, 消息, 错误码)；处置包为 None 时调用方按错误码走失败分支。
        """
        with self._lock:
            normalized, message, code = self._normalize(payload)
            if normalized is None:
                return None, message, code

            fingerprint = _fingerprint(normalized)
            existing = self._find_existing(normalized["采集批次"], normalized["监控对象"])
            if existing is not None and existing.get("内容指纹") == fingerprint:
                # 并发或连续两次完全相同的提交：只保留先成功的版本。
                raise PackageConflictError(
                    "相同的告警关联处置数据包已提交，仅保留首个成功版本", dict(existing))

            if existing is None:
                package = self._build_package(normalized, fingerprint)
                store.rows(PACKAGE_MODULE).append(package)
                return package, "告警关联处置数据包已生成", None

            # 同一批次/对象的后续提交带有新的触发内容：并入既有主事件明细，不重复建包。
            merged = self._merge_into(existing, normalized, fingerprint)
            return merged, "后续触发已归入既有处置主事件，处置包版本已更新", None

    # ------------------------------------------------------------- 内部归并
    def _normalize(
        self, payload: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, str, str | None]:
        missing = [field for field in PACKAGE_REQUIRED_FIELDS if not str(payload.get(field) or "").strip()]
        snapshot = payload.get("监控事件快照")
        if not isinstance(snapshot, dict):
            missing.append("监控事件快照")
        if missing:
            return None, f"缺少必填字段：{'、'.join(missing)}", CODE_MISSING_FIELD

        batch = str(payload["采集批次"]).strip()
        target = str(payload["监控对象"]).strip()

        snapshot_missing = [
            field for field in SNAPSHOT_REQUIRED_FIELDS
            if not str(snapshot.get(field) or "").strip()
        ]
        if snapshot_missing:
            return (
                None,
                f"监控事件快照缺少必填字段：{'、'.join(snapshot_missing)}",
                CODE_SNAPSHOT_MISSING,
            )

        hits_raw = payload.get("规则命中明细")
        if not isinstance(hits_raw, list) or not hits_raw:
            return None, "规则命中明细为空，未关联到事件的规则不能进入处置包", CODE_UNASSOCIATED_RULE

        alert_rows = store.rows(MODULE)
        hits: list[dict[str, Any]] = []
        for index, hit in enumerate(hits_raw):
            if not isinstance(hit, dict):
                return None, f"第 {index + 1} 条规则命中格式不正确", CODE_UNASSOCIATED_RULE
            hit_missing = [field for field in HIT_REQUIRED_FIELDS if not str(hit.get(field) or "").strip()]
            if hit_missing:
                return (
                    None,
                    f"第 {index + 1} 条规则命中缺少字段：{'、'.join(hit_missing)}",
                    CODE_MISSING_FIELD,
                )
            rule_no = str(hit["规则编号"]).strip()
            rule = next((row for row in alert_rows if str(row.get("规则编号")) == rule_no), None)
            # 未关联到告警事件（规则不存在）的规则不能进入处置包。
            if rule is None:
                return (
                    None,
                    f"规则 {rule_no} 未关联到告警事件，不能进入处置包",
                    CODE_UNASSOCIATED_RULE,
                )
            hit_target = str(hit["监控对象"]).strip()
            if hit_target != target:
                return (
                    None,
                    f"规则 {rule_no} 的监控对象 {hit_target} 与处置包监控对象 {target} 不一致",
                    CODE_UNASSOCIATED_RULE,
                )
            event_type = str(hit.get("事件类型") or EVENT_TRIGGER).strip()
            if event_type not in EVENT_TYPES:
                return None, f"规则 {rule_no} 的事件类型 {event_type} 不在允许范围内", CODE_UNASSOCIATED_RULE
            hits.append({
                "命中编号": str(hit.get("命中编号") or f"{rule_no}-H{index + 1}").strip(),
                "规则编号": rule_no,
                "监控对象": hit_target,
                "告警条件": str(hit.get("告警条件") or rule.get("告警条件") or "").strip(),
                "事件类型": event_type,
                "触发时间": str(hit.get("触发时间") or _now()).strip(),
                "序列": _int(hit.get("序列"), index + 1),
                "错误次数": _int(hit.get("错误次数"), 1),
                "明细说明": str(hit.get("明细说明") or "").strip(),
            })

        normalized_snapshot = {field: snapshot.get(field) for field in SNAPSHOT_REQUIRED_FIELDS}
        normalized_snapshot.update(
            {key: value for key, value in snapshot.items() if key not in SNAPSHOT_REQUIRED_FIELDS}
        )
        return {
            "采集批次": batch,
            "监控对象": target,
            "规则命中明细": hits,
            "监控事件快照": normalized_snapshot,
        }, "", None

    def _find_existing(self, batch: str, target: str) -> dict[str, Any] | None:
        for row in store.rows(PACKAGE_MODULE):
            if row.get("采集批次") == batch and row.get("监控对象") == target:
                return row
        return None

    def _next_id(self) -> int:
        return max((_int(row.get("id")) for row in store.rows(PACKAGE_MODULE)), default=0) + 1

    def _build_package(self, normalized: dict[str, Any], fingerprint: str) -> dict[str, Any]:
        package_id = self._next_id()
        package_no = f"AAP-{package_id:04d}"
        main_events = self._build_main_events(normalized["规则命中明细"])
        snapshot = self._build_snapshot(normalized, package_no, main_events)
        package = {
            "id": package_id,
            "处置包编号": package_no,
            "采集批次": normalized["采集批次"],
            "监控对象": normalized["监控对象"],
            "版本": 1,
            "处置主事件": main_events,
            "监控事件快照": snapshot,
            "规则命中总数": len(normalized["规则命中明细"]),
            "主事件数": len(main_events),
            "已关闭数": sum(1 for event in main_events if event["处置状态"] == STATE_CLOSED),
            "已恢复数": sum(1 for event in main_events if event["处置状态"] == STATE_RECOVERED),
            "最终处置状态": self._package_state(main_events),
            "创建时间": _now(),
            "更新时间": _now(),
            "内容指纹": fingerprint,
        }
        return package

    def _build_main_events(self, hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """按 监控对象+规则编号+告警条件 归并命中，重复触发只追加明细。"""
        grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        order: list[tuple[str, str, str]] = []
        for hit in sorted(hits, key=lambda item: (item["序列"], item["触发时间"])):
            key = (hit["监控对象"], hit["规则编号"], hit["告警条件"])
            if key not in grouped:
                grouped[key] = []
                order.append(key)
            grouped[key].append(hit)

        events: list[dict[str, Any]] = []
        for index, key in enumerate(order, start=1):
            group_hits = grouped[key]
            target, rule_no, condition = key
            lifecycle = [hit for hit in group_hits if hit["事件类型"] in LIFECYCLE_EVENTS]
            if lifecycle:
                # 关闭/恢复先后冲突时，以最后到达的生命周期事件作为最终处置状态。
                final_hit = max(lifecycle, key=lambda item: (item["序列"], item["触发时间"]))
                state = STATE_CLOSED if final_hit["事件类型"] == EVENT_CLOSE else STATE_RECOVERED
            else:
                state = STATE_PROCESSING
            times = [str(hit["触发时间"]) for hit in group_hits]
            events.append({
                "主事件编号": f"AME-{index:04d}",
                "监控对象": target,
                "规则编号": rule_no,
                "告警条件": condition,
                "命中次数": len(group_hits),
                "事件明细": [
                    {
                        "命中编号": hit["命中编号"],
                        "事件类型": hit["事件类型"],
                        "触发时间": hit["触发时间"],
                        "序列": hit["序列"],
                        "错误次数": hit["错误次数"],
                        "明细说明": hit["明细说明"],
                    }
                    for hit in group_hits
                ],
                "时间范围": {"开始": min(times), "结束": max(times)},
                "错误次数": sum(_int(hit["错误次数"]) for hit in group_hits),
                "处置状态": state,
            })
        return events

    def _build_snapshot(
        self, normalized: dict[str, Any], package_no: str, main_events: list[dict[str, Any]]
    ) -> dict[str, Any]:
        # 处置包与监控事件快照一起写入：快照随包构建、随包持久化，不允许只写一半。
        submitted = dict(normalized["监控事件快照"])
        times = [
            str(hit["触发时间"])
            for event in main_events for hit in event["事件明细"]
        ]
        snapshot = {
            "快照编号": f"SNAP-{package_no}",
            "采集批次": normalized["采集批次"],
            "监控对象": normalized["监控对象"],
            "事件时间范围": submitted.get("事件时间范围") or {
                "开始": min(times) if times else _now(),
                "结束": max(times) if times else _now(),
            },
            "错误次数": _int(submitted.get("错误次数")),
            "主事件数": len(main_events),
            "规则命中总数": len(normalized["规则命中明细"]),
            "快照时间": _now(),
        }
        snapshot.update(
            {key: value for key, value in submitted.items() if key not in snapshot}
        )
        return snapshot

    def _package_state(self, main_events: list[dict[str, Any]]) -> str:
        if any(event["处置状态"] == STATE_PROCESSING for event in main_events):
            return STATE_PROCESSING
        if any(event["处置状态"] == STATE_CLOSED for event in main_events):
            return STATE_CLOSED
        return STATE_RECOVERED

    def _merge_into(
        self, existing: dict[str, Any], normalized: dict[str, Any], fingerprint: str
    ) -> dict[str, Any]:
        """后续触发并入既有处置包：主事件去重，新命中写入明细，版本递增。"""
        known = {
            (hit["命中编号"], event["规则编号"], hit["序列"])
            for event in existing.get("处置主事件", [])
            for hit in event.get("事件明细", [])
        }
        new_hits: list[dict[str, Any]] = []
        # 先把既有明细还原成归并输入，再与新命中一起重新归并。
        for event in existing.get("处置主事件", []):
            for detail in event.get("事件明细", []):
                new_hits.append({
                    "命中编号": detail["命中编号"],
                    "规则编号": event["规则编号"],
                    "监控对象": existing["监控对象"],
                    "告警条件": event["告警条件"],
                    "事件类型": detail["事件类型"],
                    "触发时间": detail["触发时间"],
                    "序列": detail["序列"],
                    "错误次数": detail["错误次数"],
                    "明细说明": detail.get("明细说明", ""),
                })
        for hit in normalized["规则命中明细"]:
            signature = (hit["命中编号"], hit["规则编号"], hit["序列"])
            if signature not in known:
                new_hits.append(hit)

        main_events = self._build_main_events(new_hits)
        existing["处置主事件"] = main_events
        existing["监控事件快照"] = self._build_snapshot(normalized, existing["处置包编号"], main_events)
        existing["规则命中总数"] = len(new_hits)
        existing["主事件数"] = len(main_events)
        existing["已关闭数"] = sum(1 for event in main_events if event["处置状态"] == STATE_CLOSED)
        existing["已恢复数"] = sum(1 for event in main_events if event["处置状态"] == STATE_RECOVERED)
        existing["最终处置状态"] = self._package_state(main_events)
        existing["版本"] = _int(existing.get("版本")) + 1
        existing["更新时间"] = _now()
        existing["内容指纹"] = fingerprint
        return existing


# 路由层与运行监控共用同一个服务实例（同一把锁、同一份视图）。
alert_package_service = AlertPackageService()
