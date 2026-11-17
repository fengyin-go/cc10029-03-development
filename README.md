# 智能爬虫采集平台

面向网页爬取、API接入、增量抓取、反爬对抗与采集质量校验的数据采集平台。

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/            每个业务模块一个页面
│   ├── src/api/              统一请求封装
│   ├── src/stores/           会话与筛选状态
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/          每个业务模块一组接口
│   ├── app/services/         业务规则与状态流转
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

### 前端

```bash
cd frontend
npm ci
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 采集目标 | `targetsite` | 目标站点 | 站点编号、站点名称、入口URL |
| 抽取规则 | `selector` | 选择器规则 | 规则编号、归属站点、列表选择器 |
| 爬虫引擎 | `crawler` | 爬虫任务 | 任务编号、任务名称、关联站点 |
| 代理池 | `proxy` | 代理节点 | 节点编号、IP地址、端口号 |
| 反爬对抗 | `antiblock` | 反爬策略 | 策略编号、策略名称、触发条件 |
| 定时调度 | `schedule` | 调度计划 | 计划编号、关联任务、Cron表达式 |
| 数据提取 | `extractor` | 提取模板 | 模板编号、模板名称、输入URL |
| 采集校验 | `validate` | 校验规则 | 规则编号、校验字段、期望格式 |
| 失败重试 | `retry` | 重试策略 | 策略编号、适用任务、最大重试 |
| 存储落地 | `storage` | 存储配置 | 配置编号、存储类型、连接信息 |
| 重复去重 | `dedup` | 去重策略 | 策略编号、业务键列、去重算法 |
| 质量报告 | `quality` | 质量指标 | 指标编号、指标名称、统计口径 |
| 运行监控 | `monitor` | 监控大盘 | 大盘编号、关联任务、采集速率 |
| 告警中心 | `alert` | 告警规则 | 规则编号、监控对象、告警条件 |
| 采集API | `apigate` | API配置 | 配置编号、端点路径、请求方法 |
| 历史归档 | `archive` | 归档策略 | 策略编号、数据来源、归档周期 |
| 模板市场 | `template` | 采集模板 | 模板编号、模板名称、适用站点 |
| 采集流程 | `flowline` | 流程编排 | 流程编号、流程名称、步骤序列 |

## 约定

- 每个模块的前端页面在 `frontend/src/views/<模块>/index.vue`，后端接口在
  `backend/app/routers/<模块>.py`，业务规则在 `backend/app/services/<模块>.py`。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

## 告警关联处置数据包

告警中心按「采集批次 + 监控对象」归并重复触发的告警规则，生成可处置的事件集合，
实现在 `backend/app/services/alert_package.py`：

- `POST /api/alert/packages`：提交处置包，处置包与监控事件快照一起写入；未关联到告警
  事件的规则返回 `RULE_NOT_ASSOCIATED`，不能进入处置包。
- 同一监控对象连续触发相同告警只保留一个处置主事件，后续触发写入事件明细、版本递增，
  不重复建包；关闭/恢复命中同一主事件冲突时，以最后事件给出唯一最终处置状态。
- 相同内容的并发或连续重复提交只保留一个成功版本，冲突返回 `409` 与
  `PACKAGE_VERSION_CONFLICT`，响应回指首个成功版本。
- `GET /api/alert/packages/dashboard` 与 `GET /api/alert/packages`：结果页看板与列表。
- `GET /api/monitor/alert-events`：运行监控读取处置包生成监控事件清单，事件的时间范围、
  错误次数与处置主事件完全一致，结论同步自告警中心同一份成功版本。
- 既有告警规则接口（字段、`{ok,message,entry}` 契约、错误码）保持不变。

领域：数据工程
子方向：数据采集、爬虫与RPA
