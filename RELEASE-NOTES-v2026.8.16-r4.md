# R4 发布说明（2026-08-16）

- 固定 PPTX 画布为 `12192000 × 6858000`，类型为 `screen16x9`。
- PPTX 默认语言为 `zh-CN`，默认中文字体为微软雅黑。
- 固定状态、水印、母版与 HTML 静态文案使用简体中文。
- 新增 OOXML、母版、主题、HTML 静态文本和可见文本闭包负控。
- 未获人工放行的输出保持 `REVIEW_DRAFT` 和可见“审阅稿”标记。
- 旧 MIT 实体保留完整许可与逐实体来源；R4 修改及组合文件改以
  GPL-3.0-only 分发。
- 源码布局迁移到 `package/`，移除不再分发的历史 payload/recovery 路径。

本树状态为 `PUBLIC-BRANCH-DRAFT-PR-READY`；远端执行状态以
`PUBLICATION.json` 为准。
