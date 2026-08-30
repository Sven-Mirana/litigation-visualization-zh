# 诉讼可视化 Skill 包 R4

作者：李时瑀律师  
仓库主许可证：`GPL-3.0-only`  
版本日期：2026-08-16

R4 默认生成原生可编辑 PPTX，离线 HTML 需要显式请求。两种格式共用一个闭合
DeliveryIR；任一请求格式失败时，不得提交半成品。没有人工放行收据时，输出状态
固定为 `REVIEW_DRAFT`，可见标记为“审阅稿”。

## 许可沿革

公开历史版本 `v2026.07.28` 的 MIT 权利继续保留。原样 MIT 文件、基于 MIT 的
修改文件、R4 新增 GPL 文件及非内嵌依赖均逐项登记在
`LICENSE-PROVENANCE.json`；完整 MIT 文本见 `LICENSES/MIT.txt`，主 GPL 文本见
`LICENSE`。

## 依赖安装

本包不 vendor、下载或全局安装第三方依赖。请在包目录外建立隔离环境：

```bash
python3 -m venv /path/outside-package/lv-r4-venv
/path/outside-package/lv-r4-venv/bin/pip install \
  -r requirements-client-delivery.txt
```

PPTX 路径使用 `python-pptx 1.0.2`、`Pillow 12.2.0` 与
`jsonschema 4.26.0`；请求 HTML 时还使用 `Playwright 1.59.0`，浏览器由宿主
提供。生产路径不得使用 `@oai/artifact-tool`、Codex 私有模块缓存或
`RUNTIME_NODE*` 注入。

## 运行语义

- `tools/run_vis.py`：冻结 S1 路径；失败收据为 v1。
- `tools/run_client_delivery.py`：R4 客户审阅稿路径；失败收据为 v2。
- `client_delivery/`：输入门、DeliveryIR、PPTX/HTML writer 与验证器。
- `viz-engine/`：两个执行文件；本发行包不包含 recovery 脚本。
- `fixtures/sample-case/`：四个合成测试文件，不得替换为实际案件材料后提交。

## 专业边界

成功生成或测试 PASS 不等于事实正确、法律结论正确、隐私放行、客户交付或法院
提交。客户交付必须由获授权人类绑定确切产物哈希，逐项确认事实、证据、现行法、
隐私、客户标签与放行权限。
