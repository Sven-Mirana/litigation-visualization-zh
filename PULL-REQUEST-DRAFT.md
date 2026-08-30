# Draft PR: R4 简体中文 GPL-3.0-only 更新

## 基线与目标

- 基线：公开 `main`，commit `dedb6402fbe74958062a2d2126dda52411095ee5`，
  tag `v2026.07.28`，93 个 Git 跟踪文件，MIT。
- 目标分支：`codex/r4-gpl3-update-20260816`。
- PR 模式：Draft；先让 CI 与人工许可复核通过，再决定是否转 Ready。
- 远端动作：本树构建时尚未推送分支、尚未创建 PR。

## 结构性升级

这是旧 93 文件树到 R4 精简公开树的结构迁移，不是原路径的无差别覆盖：

| 旧入口或目录 | R4 位置或处理 |
| --- | --- |
| `tools/run_vis.py` | `package/tools/run_vis.py` |
| `viz-engine/mother-build_t4.py` | `package/viz-engine/mother-build_t4.py` |
| `viz-engine/mother-render_t4.py` | `package/viz-engine/mother-render_t4.py` |
| `payload-legacy-skill/` | 不再分发；不是运行依赖 |
| `payload-frozen-contract-r2/` | 不再分发；公开契约改放 `references/` |
| recovery 两脚本 | 不再分发；R4 runner 不依赖 |
| 旧 evidence/与本地交付封册 | 不迁移；CI 重新生成验证证据 |

调用旧路径的使用方必须显式迁移，不能静默回退。

## 许可迁移

仓库默认许可变为 GPL-3.0-only，但 `v2026.07.28` 已授予的 MIT 权利不撤销。
原样 MIT 组件、基于 MIT 的修改文件、完整旧 MIT 文本和逐实体哈希见
`LICENSES/MIT.txt`、`NOTICE` 与 `LICENSE-PROVENANCE.json`。

## 合并前门

- `SHA256SUMS.txt` 全部通过。
- 公开隐私门通过：零真实案卷、零本机路径、零内部协作标识、零 symlink/bytecode。
- macOS + 真实 Chrome：74/74，0 failure、0 error、0 skip。
- 根与 package 的 GPL、MIT notice、逐实体账本人工复核通过。
