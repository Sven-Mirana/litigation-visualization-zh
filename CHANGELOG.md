
# Changelog

## 2026.08.30 r2 timeline demo

版本：`2026.08.30-r2-timeline-demo-gpl3`。

- 新增独立固定三事件 DeliveryIR 演示，输出 Control/A/B 各一份 PPTX 和 HTML。
- 新增原生可编辑三页 draw.io 导出；只转换演示时间线页，不声称通用案件格式支持。
- r2 引擎副本隔离在 `package/timeline_demo/r2_engine/`；原 R4 生产运行代码、
  两条生产入口及生产依赖锁保持不变。
- 新增独立演示依赖锁，使用 Pillow 12.3.0 与 typing-extensions 4.16.0。
- 保留历史 MIT 权利与逐实体来源；不复制内部安装树、历史 payload 或 donor 代码。
- 所有演示维持 `synthetic / REVIEW_DRAFT`；真实案件、客户/法院外发和人工编辑
  验收不在演示结论范围。实际发布结果以树外远端回读收据为准。

## 2026.08.16 R4

- 固定 PPTX 画布为 `12192000 × 6858000` 且类型为 `screen16x9`。
- 将 PPTX 默认文本样式语言闭合为 `zh-CN`，字体闭合为微软雅黑。
- 将固定状态、水印、母版和 HTML 静态文案本地化为简体中文。
- 为 OOXML 元数据、母版、主题、HTML 静态文本和可见文本闭包增加判别负控。
- 保持输出默认 `REVIEW_DRAFT`，可见状态“审阅稿”。
