# 诉讼可视化：r3 生产入口接受真实案件

版本：`2026.10.12-r3-real-case-gpl3`。

## r3：可直接处理真实案件

- 生产入口 `package/tools/run_client_delivery.py` 接受真实案件，实名或脱敏材料均可，
  无需事先授权或脱敏。交付 profile 的 `data_class` 新增 `identified`（真实案件原样
  材料），与 `deidentified`、`synthetic` 并列；DeliveryIR、产物清单 v2、失败收据 v2
  与 RenderIR 合同同步放开。
- `case_ref` 不再要求匿名，只需是稳定的 ASCII 编号；中文案号写在 `matter_label`。
- 技术门不变：TEXT PASS、冻结 07 哈希、跨案、A01-A09 锚集任一不闭合仍 fail closed，
  不留产物；产物仍标“审阅稿”。固定合成演示不变。
- 报错更明确：PPTX 布局溢出时按页码顺序一次列出所有溢出页（页码、标题、来源），并提示缩短条目或改用
  `--format html`；本机路径扫描的报错写明与案件是否真实、是否脱敏无关。
- 新增 5 项回归测试，生产回归共 79 项。输入格式参见 `package/fixtures/sample-case/`
  与 `SKILL.md`，完整说明见 `RELEASE-NOTES-r3.md`。

## r2 固定时间线演示

r2 新增一个独立的固定合成演示：用同一份三事件 DeliveryIR 比较 Control、A、B
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
覆盖到原生产环境。r3 在 macOS 本机的包外环境中（依赖为两份锁定版本），生产回归 79 项、
演示测试 15 项通过；实际 CLI 七个产物与批准样例字节一致。详见 `VALIDATION.json`，不推定
Linux/Windows 或桌面软件人工往返已验证。

## 生产契约

生产入口在同案 `TEXT PASS`、独立冻结 07 与 A01-A09 锚集闭合后，生成原生可编辑
PPTX 与单文件离线 HTML；真实案件实名或脱敏材料均可直接使用，无需事先授权或脱敏。
未获得绑定确切产物哈希的有效人工放行收据时，状态保持 `REVIEW_DRAFT`。固定合成演示
只用内置样例，真实案件请走生产入口。

## 来源、许可与发布状态

r3 在已发布的 `v2026.08.30-r2` 主分支（commit
`e8452288f3b1a0843278ec27d1b489ce0fb35834`）上增量修改；r2 基于已公开 R4 分支
`850494c404d91c7f9b891c358671a2a0051e9119` 的精简公开树增量构建，不分发本机完整安装树、历史 payload、内部治理记录或真实案件。
`PULL-REQUEST-DRAFT.md` 是 R4 历史迁移说明，不是本版本当前发布收据。

主许可证为 `GPL-3.0-only`；旧公开 `v2026.07.28` 的 MIT 权利继续有效。完整许可、
MIT 通知和逐实体来源见 `LICENSE`、`LICENSES/MIT.txt`、`NOTICE` 与
`LICENSE-PROVENANCE.json`。没有复制 donor 仓库代码或内嵌 draw.io viewer。

`PUBLICATION.json` 记录本轮构建时的发布意图和历史基线；实际推送、合并或 Release
须以构建树外的远端回读收据为准。本文不宣称这些动作已经完成。源码分发、安装和
演示生成均不等于客户交付、GEO 激活或法院提交。
