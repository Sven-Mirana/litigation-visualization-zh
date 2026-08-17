---
name: litigation-visualization
display_name: 诉讼可视化Skill包
description: 从来源绑定、隐私审查通过的冻结诉讼事实生成原生可编辑 PPTX 或单文件离线 HTML；默认 REVIEW_DRAFT 并显示“审阅稿”，要求人工事实、法律、隐私和客户放行。
version: 2026-08-16-r4-zh-cn-gpl3
author: 李时瑀律师
license: GPL-3.0-only
---

# 诉讼可视化 Skill 包（R4）

## 用途

把来源绑定的诉讼事实模型转换为时间线、主体关系、证据矩阵等可编辑客户审阅稿。
本包不提供法律意见，也不替代律师对事实、证据、现行法、隐私及最终交付的判断。

## 核心契约

- VIS 默认关闭；唯一输入为同案独立冻结 07 与 A01-A09 精确锚集。四视图不得
  回写文本链；非法日期、事件超限、跨案或冻结快照失配一律 fail closed。
- 封装前执行隐私门；真实案件原文、本机路径与内部协作记录不得进入分发包或 Git。
- GEO activation/public_projection/release 保持 false，除非另行明确审批。

## 内容与执行入口

- `tools/run_vis.py`：冻结 S1 四图 runner；失败收据使用 v1 schema。
- `tools/run_client_delivery.py`：R4 客户审阅稿 runner；失败收据使用 v2 schema。
- `client_delivery/`：严格输入门、DeliveryIR、PPTX/HTML writer 与验证器。
- `viz-engine/`：`mother-render_t4.py` 为原样 MIT 组件；`mother-build_t4.py` 和
  `run_vis.py` 基于旧 MIT 文件修改，保留 MIT 通知，R4 修改及组合文件按
  GPL-3.0-only 分发。

## PPTX 与 HTML

- PPTX 必须由隔离环境中的 `python-pptx==1.0.2` 生成原生可编辑对象，并通过
  固定 ZIP 元数据的 OOXML 归一化实现确定性。
- 生产路径不得依赖 `@oai/artifact-tool`、Codex 私有 Node 路径或
  `RUNTIME_NODE*` 注入。
- HTML 必须单文件、零脚本、零 CDN、零外链字体并可离线打印。
- PPTX 与 HTML 使用同一 DeliveryIR；任何请求格式失败，整个事务不提交。

## 许可与边界

主许可证为 `GPL-3.0-only`。旧 MIT 文件、修改来源和完整 MIT 通知见
`LICENSE-PROVENANCE.json`、`NOTICE` 与 `LICENSES/MIT.txt`。案件事实、证据、
个人信息、商标及其他第三方材料不会因与程序同目录而变成 GPL。

公开源码不等于自动安装、真实案件外发、客户放行、GEO 激活或法院提交；这些动作
需要各自的人类授权与证据。
