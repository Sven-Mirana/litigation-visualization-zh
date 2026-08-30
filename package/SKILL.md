---
name: litigation-visualization
display_name: 诉讼可视化Skill包
description: 沿用 R4 门从冻结诉讼事实生成 PPTX 或离线 HTML；另提供固定三事件 Control/A/B 与三页 draw.io 合成演示。演示不是通用案件入口，全部未放行产物保持 REVIEW_DRAFT。
version: 2026.08.30-r2-timeline-demo-gpl3
author: 李时瑀律师
license: GPL-3.0-only
---

# 诉讼可视化 Skill 包（R4 生产入口 + r2 固定演示）

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
- `tools/run_timeline_demo.py`：只接受包内固定三事件 IR 的演示入口。
- `timeline_demo/r2_engine/`：隔离的 r2 演示副本，不替换 `client_delivery/` 或
  `viz-engine/` 的 R4 生产代码。
- `viz-engine/`：`mother-render_t4.py` 为原样 MIT 组件；`mother-build_t4.py` 和
  `run_vis.py` 基于旧 MIT 文件修改，保留 MIT 通知，R4 修改及组合文件按
  GPL-3.0-only 分发。

## 固定三事件演示

Control（竖轨卡片）、A（横向日期比例轴）、B（纵向卷宗登记簿）使用同一固定 IR，
生成各一份 PPTX 与 HTML，并导出一份包含三种时间线页的原生可编辑 `.drawio`。
文字、日期、顺序及 source/semantic IDs 不因版式而改写；细矩形线条不冒充节点
连接器。演示始终为 `synthetic / REVIEW_DRAFT`。

演示依赖单列于 `requirements-timeline-demo.txt`（Pillow 12.3.0、
typing-extensions 4.16.0），须在独立的包外环境安装。原
`requirements-client-delivery.txt` 与两条生产入口保持不变。

禁止以本入口处理任意外部事实或真实案件；禁止将演示描述为通用 A/B 或 draw.io
格式支持。固定样例成功、结构校验或截图不等于复杂案件覆盖、人工打开/编辑/另存
验收、客户交付或法院放行。

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
