# 诉讼可视化：固定时间线 r2 演示

版本：`2026.08.30-r2-timeline-demo-gpl3`。

本次新增一个独立的固定合成演示：用同一份三事件 DeliveryIR 比较 Control、A、B
三种时间线版式，并生成原生可编辑的三页 draw.io 文件。既有 R4 生产入口、生产
引擎和 `package/requirements-client-delivery.txt` 保持不变；本次没有把 A/B 或
draw.io 加入通用客户交付格式。

## 新演示能做什么

- Control：旧版竖轨卡片版式；A：横向日期比例轴；B：纵向卷宗登记簿。
- 三版只改变版式，消费相同的固定三事件、文字、日期、来源与语义标识。
- 生成 Control/A/B 各一份 PPTX 和离线 HTML，共六个主体产物；另生成包含三种
  时间线页的原生 `.drawio` 文件，不是三份完整简报的转换。
- draw.io 中的文字和形状可编辑；细轴线/引线保持原生细矩形，不宣称是绑定节点的
  连接器。预览图不能替代可编辑文件。
- 演示只接受包内固定合成 IR，不接受真实案件或任意事实输入。它不是通用 A/B
  排版器、通用 PPTX 转换器或 `run_client_delivery.py --format drawio`。

全部演示产物保持 `synthetic / REVIEW_DRAFT`，可见状态为“审阅稿”。固定三事件
通过不证明复杂案件覆盖、事实/法律正确性、WPS/PowerPoint 或 draw.io Desktop
人工打开、编辑、另存及打印验收。

## 入口与环境

- 固定演示入口：`package/tools/run_timeline_demo.py`。
- 隔离演示引擎：`package/timeline_demo/r2_engine/`；不替换生产模块。
- 演示依赖：`package/requirements-timeline-demo.txt`，其中 Pillow 为 12.3.0、
  typing-extensions 为 4.16.0；第三方依赖不内嵌。
- 原生产入口仍为 `package/tools/run_vis.py` 和
  `package/tools/run_client_delivery.py`；原生产依赖锁单独保留。

Python 3.12 示例（演示与生产使用不同的包外虚拟环境）：

```bash
python3 -m venv /tmp/lv-timeline-demo-venv
/tmp/lv-timeline-demo-venv/bin/pip install -r package/requirements-timeline-demo.txt
/tmp/lv-timeline-demo-venv/bin/python -B package/tools/run_timeline_demo.py --help
/tmp/lv-timeline-demo-venv/bin/python -B package/tools/run_timeline_demo.py --out ../timeline-demo-output
```

输出目录必须尚不存在，其父目录必须存在且路径不能含符号链接。不要把演示依赖
覆盖到原生产环境。本次在 macOS 的全新包外环境中，生产回归 74 项、演示测试 15 项
通过；实际 CLI 七个产物与批准样例字节一致。详见 `VALIDATION.json`，不推定
Linux/Windows 或桌面软件人工往返已验证。

## 原生产契约不变

R4 仍只在同案 `TEXT PASS`、独立冻结 07 与 A01-A09 锚集闭合后，生成原生可编辑
PPTX 与单文件离线 HTML。未获得绑定确切产物哈希的有效人工放行收据时，状态保持
`REVIEW_DRAFT`。固定合成演示不能绕过真实案件的事实、证据、法律、隐私和人工门。

## 来源、许可与发布状态

本更新基于已公开 R4 分支 `850494c404d91c7f9b891c358671a2a0051e9119` 的精简
公开树增量构建，不分发本机完整安装树、历史 payload、内部治理记录或真实案件。
`PULL-REQUEST-DRAFT.md` 是 R4 历史迁移说明，不是本版本当前发布收据。

主许可证为 `GPL-3.0-only`；旧公开 `v2026.07.28` 的 MIT 权利继续有效。完整许可、
MIT 通知和逐实体来源见 `LICENSE`、`LICENSES/MIT.txt`、`NOTICE` 与
`LICENSE-PROVENANCE.json`。没有复制 donor 仓库代码或内嵌 draw.io viewer。

`PUBLICATION.json` 记录本轮构建时的发布意图和历史基线；实际推送、合并或 Release
须以构建树外的远端回读收据为准。本文不宣称这些动作已经完成。源码分发、安装和
演示生成均不等于真实案件外发、客户交付、GEO 激活或法院提交。
