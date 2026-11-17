"""告警中心接口：维护告警规则，覆盖提交校验、启用配置、停用配置等动作。

新增告警关联处置数据包接口：按采集批次归并规则命中、与监控事件快照一起提交，
并给运行监控提供监控事件清单数据源。既有规则接口的字段与错误码保持不变。
"""
from __future__ import annotations

import csv
import io

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.schemas import ActionPayload, ActionResult, PageResult
from app.services.alert import AlertService
from app.services.alert_package import (
    PackageConflictError,
    alert_package_service,
)

router = APIRouter(prefix="/api/alert", tags=["告警中心"])

service = AlertService()

LIST_FIELDS = ["规则编号", "监控对象", "告警条件", "通知渠道", "通知模板", "重复间隔", "生效时段", "值班人员"]
STATUSES = ["草稿", "待校验", "已启用", "已停用"]

PACKAGE_FILTER_FIELDS = ["处置包编号", "采集批次", "监控对象", "最终处置状态"]


def query_filters(request: Request) -> dict[str, str]:
    """只接受当前模块声明过的字段，忽略分页等保留参数。"""
    return {
        key: value.strip()
        for key, value in request.query_params.items()
        if key in LIST_FIELDS and value.strip()
    }


def package_query_filters(request: Request) -> dict[str, str]:
    return {
        key: value.strip()
        for key, value in request.query_params.items()
        if key in PACKAGE_FILTER_FIELDS and value.strip()
    }


@router.get("", response_model=PageResult[dict])
def list_entries(
    request: Request,
    keyword: str | None = Query(default=None, description="按规则编号检索"),
    status: str | None = Query(default=None, description="草稿、待校验、已启用、已停用"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
) -> PageResult[dict]:
    """按页面字段、规则编号关键字与状态过滤告警中心列表。"""
    items, total = service.list_entries(
        filters=query_filters(request), keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries(
    request: Request,
    keyword: str | None = Query(default=None),
    status: str | None = Query(default=None),
) -> StreamingResponse:
    """下载当前筛选条件下的 UTF-8 CSV；必须声明在 /{entry_id} 之前。"""
    items, _ = service.list_entries(
        filters=query_filters(request), keyword=keyword, status=status, page=1, size=1000000)
    output = io.StringIO()
    output.write("﻿")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["id", *LIST_FIELDS, "status"])
    for item in items:
        row = []
        for value in [item.get("id"), *(item.get(field, "") for field in LIST_FIELDS), item.get("status", "")]:
            text = "" if value is None else str(value)
            row.append("'" + text if text.startswith(("=", "+", "-", "@")) else text)
        writer.writerow(row)
    return StreamingResponse(
        iter([output.getvalue()]), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="alert.csv"'})


# ----------------------------------------------------------- 告警关联处置数据包
@router.get("/packages/dashboard")
def package_dashboard() -> dict:
    """告警中心结果页看板：按最终处置状态分组呈现处置包与汇总卡片。"""
    return alert_package_service.dashboard()


@router.get("/packages", response_model=PageResult[dict])
def list_packages(
    request: Request,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
) -> PageResult[dict]:
    """按处置包编号、采集批次、监控对象、最终处置状态过滤关联处置包列表。"""
    items, total = alert_package_service.list_packages(
        filters=package_query_filters(request), page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.post("/packages", response_model=ActionResult)
def submit_package(payload: dict[str, object]) -> ActionResult:
    """提交告警关联处置数据包：处置包与监控事件快照一起写入。

    未关联到事件的规则不能进入处置包；相同内容的并发/连续重复提交只保留一个成功版本。
    沿用既有动作契约 {ok, message, entry}，冲突与校验失败补充稳定错误码。
    """
    try:
        package, message, code = alert_package_service.submit_package(payload)
    except PackageConflictError as conflict:
        raise HTTPException(
            status_code=409,
            detail={
                "ok": False,
                "code": conflict.code,
                "message": str(conflict),
                "entry": conflict.package,
            },
        ) from conflict
    if package is None:
        return ActionResult(ok=False, message=message, entry={"code": code} if code else None)
    return ActionResult(ok=True, message=message, entry=package)


@router.get("/packages/{package_id}", response_model=dict)
def get_package(package_id: int) -> dict:
    """读取单个告警关联处置数据包（含主事件、命中明细与监控事件快照）。"""
    package = alert_package_service.get_package(package_id)
    if package is None:
        raise HTTPException(status_code=404, detail=f"告警关联处置数据包 {package_id} 不存在或已归档")
    return package


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条告警规则明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"告警规则 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: dict[str, object]) -> ActionResult:
    """登记一条告警规则，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="告警规则已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: ActionPayload) -> ActionResult:
    """对单条告警规则执行提交校验、启用配置、停用配置；不允许的动作会被拦下并说明原因。"""
    entry, message = service.run_action(entry_id, payload.action.strip())
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
