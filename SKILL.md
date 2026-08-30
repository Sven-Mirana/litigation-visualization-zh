---
name: litigation-visualization
description: 在同案 TEXT PASS 后沿用 R4 门生成 PPTX 或离线 HTML 审阅稿；另提供隔离的固定三事件 Control/A/B 时间线及三页 draw.io 演示。演示不接受真实案件，不扩展通用客户交付格式；未获人工放行的产物保持 REVIEW_DRAFT。
version: 2026.08.30-r2-timeline-demo-gpl3
author: 李时瑀律师
license: GPL-3.0-only
metadata:
  source_package_id: litigation-visualization
  client_delivery_runtime: python-pptx-1.0.2
---

# 诉讼可视化 Skill（R4 生产入口 + r2 固定合成演示）

仓库主许可为 `GPL-3.0-only`；旧 MIT 文件及修改来源保留原通知，详见
`LICENSE-PROVENANCE.json`、`NOTICE` 和 `LICENSES/MIT.txt`。程序许可不授予案件
事实、证据、个人信息、客户材料、商标或其他第三方内容的权利。

## 使用入口

- 先读取 `package/SKILL.md`。
- 冻结 S1 四图入口：`package/tools/run_vis.py`。
- R4 客户审阅稿入口：`package/tools/run_client_delivery.py`。
- 固定合成演示入口：`package/tools/run_timeline_demo.py`。只有用户请求演示
  Control/A/B 版式或三页 draw.io 时使用；不要把实际案件路由到这个入口。

## r2 演示边界

- 只读取包内固定三事件 DeliveryIR；不接受任意案件、事件或外部事实输入。
- 同一 IR 生成 Control/A/B 各一份 PPTX、HTML，再导出三页原生可编辑 draw.io。
- A 为横向日期比例轴，B 为纵向卷宗登记簿，Control 保留旧版竖轨卡片版式；
  不修改文字、日期、顺序、source/semantic IDs。
- 演示引擎位于 `package/timeline_demo/r2_engine/`，与原生产模块隔离。
  原 R4 生产代码与 `package/requirements-client-delivery.txt` 均不变；演示
  使用单独的 `package/requirements-timeline-demo.txt` 和包外环境。
- 这不是通用 A/B 排版或 draw.io 客户交付路线，不得向旧生产入口添加或虚构
  `--format drawio`。演示完成不能作为真实案件覆盖或人工编辑/另存验收证明。
- 状态始终为 `synthetic / REVIEW_DRAFT`；无真实案件放行或对外提交权限。

## 强制边界

- VIS 默认关闭；只有 `TEXT PASS` 后才能消费同案独立冻结 07 与 A01-A09 精确锚集。
- 输入缺失、哈希不符、跨案、锚集失配、隐私门失败、请求与产出格式不闭合时必须
  fail closed，且不得留下半成品。
- 上游事实、证据、现行法、隐私与人工确认是权威来源；渲染层不得反向改写。
- 生成成功、结构校验、截图预览或 agent ACK 都不是客户或法院放行。

## R4 客户交付格式

- 未指定 `--format` 时只请求原生可编辑 PPTX；显式请求 HTML 时只生成单文件
  离线 HTML；双格式请求作为一个事务共同提交。
- PPTX 使用仓库外隔离环境中的 `python-pptx==1.0.2`，不得依赖
  `@oai/artifact-tool` 或 Codex 私有运行时。
- HTML 必须单文件、零脚本、零 CDN、零外链字体并支持离线阅读和打印。
- 两种格式消费同一闭合 `DeliveryIR`，不得静默截断、缩写、重排或用截图冒充
  可编辑演示文稿。
- 没有绑定确切 profile 与产物哈希的人工放行收据时，状态保持 `REVIEW_DRAFT`，
  文件名沿用 `REVIEW-DRAFT`，每页显示“审阅稿”。

## 失败收据和发布边界

`failure-receipt-v1` 只服务冻结 S1；`failure-receipt-v2` 只服务 R4 客户交付事务。
失败收据只能证明失败、清理与零提交，不能充当成功、客户放行或法院提交证据。

`PUBLICATION.json` 是本轮构建时的发布意图和历史状态，不是推送完成证明；实际远端
动作以树外发布回读收据为准。公开源码不等于自动安装、真实案件外发、客户放行、
GEO 激活或法院提交；这些动作仍需各自的人工授权与证据。
