# 2026.08.30 r2 固定时间线演示

版本：`2026.08.30-r2-timeline-demo-gpl3`。

本版在 R4 公开树上增加隔离演示，不升级或替换既有生产运行代码。

## 新增内容

- `package/tools/run_timeline_demo.py`：只消费固定三事件合成 DeliveryIR。
- Control 竖轨卡片、A 横向日期比例轴、B 纵向卷宗登记簿；各输出 PPTX 和离线
  HTML，共六个主体产物，日期、全文、顺序与来源/语义标识一致。
- 一份三页原生可编辑 draw.io，仅含三种时间线页。形状与文字不是截图；源细线
  仍是细矩形，不冒称节点连接器。
- `package/timeline_demo/r2_engine/` 与独立的
  `package/requirements-timeline-demo.txt`；演示依赖不覆盖生产环境。

## 没有改变的边界

原 `run_vis.py`、`run_client_delivery.py`、生产引擎与生产依赖锁保持 R4 字节。
本版没有通用 A/B 案件排版、任意 PPTX 转换或 draw.io 公共客户格式路线。固定三事件
演示不接收真实案件；产物始终标记 `synthetic / REVIEW_DRAFT`。测试与预览不证明
事实/法律正确、真实案件覆盖、WPS/PowerPoint 或 draw.io Desktop 人工编辑/另存
与打印验收，也不授权客户、法院、GEO 或真实案情公开。

## 来源与发布

公开基底是 R4 分支 commit `850494c404d91c7f9b891c358671a2a0051e9119`；历史
MIT 基底是 `v2026.07.28`。MIT 原通知继续保留，新修改与组合按 GPL-3.0-only
分发；无 donor 代码、第三方依赖或 draw.io viewer 内嵌。

本文是版本内容说明，不是已推送、已合并或已发布 Release 的证明。构建状态见
`PUBLICATION.json`；确切验证、文件哈希和实际远端动作以最终封印及树外回读收据为准。
