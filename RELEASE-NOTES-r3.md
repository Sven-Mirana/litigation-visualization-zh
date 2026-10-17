# 2026.10.12 r3 真实案件输入

版本：`2026.10.12-r3-real-case-gpl3`。

本版在已发布的 `v2026.08.30-r2` 上放开生产入口对真实案件的输入限制。

## 改动

- 客户审阅稿入口 `package/tools/run_client_delivery.py` 接受真实案件：交付 profile 的
  `data_class` 新增 `identified`（真实案件原样材料），与 `deidentified`、`synthetic`
  并列。实名或脱敏材料均可，不要求事先脱敏或另行授权。
- DeliveryIR、产物清单 v2、失败收据 v2 与 RenderIR 四份合同的 `data_class` 枚举同步
  加入 `identified`；RenderIR 不再把 `real_case_data` 锁定为 false，
  `minimization_status` 增加 `not_required`。
- `case_ref` 不再要求匿名，只需是 1-64 位字母、数字或 `._-`，首位为字母或数字；中文
  案号写入 `matter_label`。`data_class` 仍为必填的三选一，非字符串取值同样按输入门拒绝。
- 报错更明确：PPTX 布局溢出时按页码顺序一次列出所有溢出页（页码、标题、来源），并提示缩短条目或改用
  `--format html`；本机路径扫描的报错写明与案件是否真实、是否脱敏无关。
- SKILL.md、README、交付合同等说明删除“授权或隐私门通过后才可运行”“真实案件须先
  脱敏”等表述，写明不得以未脱敏、未授权或属于真实案件为由拒绝，并补充输入格式要点
  （表格首尾带竖线；A01 每位主体四栏合计约 40 字以内，长信息放第七节；封面标题
  `matter_label` 约 30 字以内）。
- 新增 5 项回归测试，生产回归共 79 项：真实案件 profile 通过且 DeliveryIR 合法、四份
  合同枚举与输入门一致、实名材料端到端出件不打码、真实案件失败收据可落盘、布局溢出
  报错指明页码与处理办法。
- 公开仓库的发布门改为 `validation/check_r3_release.py`，`check_r2_release.py` 与
  `check_public_release.py` 保留为兼容入口。未改动的生产文件仍须与 R4（与
  `v2026.08.30-r2` 的生产字节相同）逐字节一致，改动的生产文件须与
  `SOURCE-BINDING.json` 登记的 r3 哈希一致。

## 没有改变的部分

- 技术门：TEXT PASS、冻结 07 哈希、跨案、A01-A09 锚集任一不闭合仍 fail closed，不留
  产物。
- 产物状态仍为 `REVIEW_DRAFT`，每页显示“审阅稿”。
- r2 固定三事件演示、演示引擎、两份依赖锁和 S1 四图入口均未改动。
- 公开仓库仍不得提交案件材料；这只约束仓库内容，不限制在本机处理真实案件。
