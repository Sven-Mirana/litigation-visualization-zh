# 诉讼可视化 R4 简体中文公开更新

R4 在同案 `TEXT PASS`、冻结 07 与 A01-A09 锚集闭合后，生成原生可编辑
PPTX 与单文件离线 HTML。固定界面、状态标记、母版语言和默认字体已适配中国大陆
简体中文环境。没有有效人工放行收据时，输出始终是 `REVIEW_DRAFT`，可见状态为
“审阅稿”。

## 发布状态

本树已达到公开分支与草稿 PR 的本地发布门，目标仓库、分支以及尚未执行的远端动作
见 `PUBLICATION.json`。本地发布就绪不表示分支已经推送或 PR 已创建，也不等于客户
交付、法院提交或真实案件材料可以公开。

仓库主许可证为 `GPL-3.0-only`，完整文本见 `LICENSE`。公开历史版本
`v2026.07.28`（commit `dedb6402fbe74958062a2d2126dda52411095ee5`）原有的
MIT 权利继续有效；原样保留或由其修改的文件、完整 MIT 文本及逐实体映射分别见
`LICENSES/MIT.txt`、`NOTICE` 和 `LICENSE-PROVENANCE.json`。

## 目录

- `package/tools/run_vis.py`：冻结 S1 四图入口。
- `package/tools/run_client_delivery.py`：R4 客户审阅稿入口。
- `package/client_delivery/`：输入门、DeliveryIR、PPTX/HTML 生产与验证。
- `package/viz-engine/`：旧 MIT 引擎及其 R4 修改版。
- `package/fixtures/sample-case/`：仅含明确标注的合成测试材料。
- `references/`：公开契约与 schema；不是案件资料。
- `validation/`：74 项回归测试和公开发布隐私门。

旧公开仓库的 93 文件布局到本树的迁移说明见 `PULL-REQUEST-DRAFT.md`。已删除的
`payload-legacy-skill/`、`payload-frozen-contract-r2/` 和 recovery 脚本不是 R4
运行依赖，任何旧路径调用方必须迁移到上面的 `package/` 入口。

## 环境与测试

- Python 3.12；依赖见 `package/requirements-client-delivery.txt`。
- 完整回归在 macOS 与 Google Chrome 完成；不得据此声称 Linux/Windows 已验证。
- 依赖只能安装在仓库外的隔离虚拟环境，本仓库不 vendor 第三方依赖。

```bash
python3 -m venv /tmp/lv-r4-venv
/tmp/lv-r4-venv/bin/pip install -r package/requirements-client-delivery.txt
PYTHONDONTWRITEBYTECODE=1 /tmp/lv-r4-venv/bin/python -B -m unittest \
  discover -s validation -p 'test*.py' -v
shasum -a 256 -c SHA256SUMS.txt
PYTHONDONTWRITEBYTECODE=1 python3 -B validation/check_public_release.py
```

任何生成成功、结构 PASS、截图或 agent 回执都不等于事实、法律、隐私、客户或
法院放行。
