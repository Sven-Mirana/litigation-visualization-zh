# 固定合成时间线演示（r2）

本模块是固定样例的可移植重放入口，不是通用 A/B 时间线功能，也不是生产交付入口。
`tools/run_client_delivery.py`、生产 `client_delivery/`、生产 `viz-engine/` 和
`requirements-client-delivery.txt` 保持原版本；演示只导入隔离的
`timeline_demo/r2_engine/client_delivery/`。
七个引擎源文件经哈希验证后，在演示专用模块命名空间直接编译加载；不修改生产
`client_delivery` 命名空间或 Python 搜索路径，也不读取引擎的缓存字节码。

## 运行

在包目录外建立 Python 虚拟环境，由操作者安装单独的
`requirements-timeline-demo.txt`。本模块不联网安装依赖、不 vendor 依赖、draw.io
viewer 或 XSD，也不需要浏览器、Node 或任何私有宿主运行时。

```sh
python -m venv /absolute/path/outside-package/demo-venv
/absolute/path/outside-package/demo-venv/bin/pip install -r package/requirements-timeline-demo.txt
/absolute/path/outside-package/demo-venv/bin/python -B package/tools/run_timeline_demo.py --out /absolute/path/outside-package/fresh-demo
```

输出目录必须不存在，父目录必须已存在、由操作者控制，且路径不能包含 symlink；
macOS 的 `/tmp` 等系统别名应先换为其规范路径。输出不得位于源包内。
最终提交使用宿主的原子 no-replace rename（macOS、支持 renameat2 的 Linux、Windows）；
不支持这一能力的宿主或文件系统会失败关闭，不降级为覆盖写入。

## 精确支持范围

- 唯一输入是 `fixtures/timeline-demo/delivery-ir.json` 原字节，SHA-256 为
  `9a5d162d532133c32877bc32c2d5add9ada348f3ff971b61e3c1424f3123b894`。
- 固定 13 页、47 个语义项、一个三事件时间线页；不接受用户 IR、真实案件、事件数量或 profile 参数。
- Control 为旧版竖轨卡片，A 为横向比例时间带，B 为纵向卷宗登记簿。
- 输出三份原生可编辑 PPTX、三份单文件离线 HTML，均精确匹配批准的 r2 产物哈希。
- 一份 draw.io 文件只有三页：从各 PPTX 的固定第 6 页原生形状导出，共 51 个原生可编辑对象。
  这不是全套 13 页导出，更不是通用 PPTX-to-draw.io 转换器。源中的细矩形继续是细矩形，
  不虚构为连接器；没有内嵌截图或 viewer。

低层 r2 引擎在本包中只作为这个已验证样例的实现快照。其他事件数量、长文本、未知日期、
其他 IR 和直接调用低层 A/B 参数均不在此模块的验证范围。已知通用路径尚有四事件 A 文本
交叠门与零/单事件 B 导线门缺口；精确 IR 白名单不是这些通用缺口已修复的声明。

## 失败关闭与可验证性

生成前校验固定 IR、七个实际导入引擎源文件及外部依赖版本。两个隐藏事务目录分别完整
生成七件产物，执行原生 OOXML、语义清单、可见文本、离线 HTML 与固定 draw.io 对象检查，
再比较全输出字节。源绑定事后不变且全部校验通过后才一次性提交 fresh 输出目录。
既有目录拒绝覆盖；任一生成或校验失败时不提交产物，临时事务目录被清理。

输出包括 `TIMELINE-DEMO-RECEIPT.json`、`drawio-export-map.json` 与同一份冻结 IR。
收据只含相对文件名、哈希和状态，不带开发者本机路径、旧候选路径或正式三根基线耦合。
编辑后的输出不再满足批准哈希，复核应失败；这不妨碍接收者编辑原生对象。

```sh
python -B -m unittest discover -s package/tests -p test_timeline_demo.py -v
```

验证的是批准字节重放加当前结构检查，不是重新执行浏览器字形测量、PowerPoint/WPS
人工编辑打印验证或 draw.io renderer QA；收据明确保留这些限制。机器状态始终
`REVIEW_DRAFT`，可见“审阅稿”；不提供真实案件适用、法律/事实完整性、客户/法院/公开
放行、安装或 formal promotion 授权。GPL-3.0-only 源代码许可与上述专业责任/验证边界
分别适用，不给 GPL 权利附加限制。
