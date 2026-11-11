---
name: cocos-ui-rebuild
description: 根据 UI 散图、设计稿和项目已有 UI 功能，生成可在 Cocos Studio 中编辑的 CSD、CSI 图集描述及 PNG/plist，并用本地 Python 生成预览和检查资源。用于新建或还原 Cocos Studio 界面；单纯解析 CSB、修改业务逻辑或生成美术素材时不使用。
---

# 散图还原 Cocos Studio UI

交付可继续编辑的控件层级、正确的图集引用和可重建的布局参数。机械操作由本地 Python 完成；不要每次让模型重新输出整份 XML、重新编写打包或校验脚本。

## 先对照已有功能

读取工程指引和相关 UI 代码，梳理数据字段、显示状态、点击事件、列表模板、模型/Spine 挂点以及已有自定义控件。已有绑定名直接复用；纯代码创建的界面按原变量和处理函数建立节点对应表。依据功能选择 Button/Text/TextBMFont/LoadingBar/ScrollView 等控件，不能只把设计稿拼成静态 Sprite。

在 sohoojs 中，动态 ScrollView 默认留空，行或列使用独立 CSD 模板。需要内嵌模板时只放一个可直接复用的 ProjectNode。节点命名、预览和接入规则见 [references/layout.md](references/layout.md#动态列表与嵌套模板)。

找到一个相近的真实 CSD 和 CSI，核对编辑器版本、资源根、设计尺寸、字体、命名与适配。用户只要求资源时，交付可接入的节点与对应表，不顺带改业务逻辑。

需要输入散图和设计稿。优先用原尺寸文件；区分设计稿像素、逻辑画布、设备截图与安全区。静态图无法确定的状态或适配规则按已有功能推定并记录。缺图按用户要求留挂点或复用工程公共图，不从设计稿抠出带背景的图片冒充原素材。

## 本地制作

读取 [references/workflow.md](references/workflow.md)，了解脚本输入、坐标和支持范围。脚本依赖 Python 3.10+ 与 Pillow，优先复用已有解释器；缺依赖时在可写目录创建虚拟环境，不修改全局 Python。

1. 使用 `scripts/cocos_ui.py inventory` 生成联系表并查看，必要时查看单图。识别素材实际内容，不能凭文件名分配颜色、标题或按钮状态。
2. 使用 `cocos_ui.py csi` 基于项目样板生成 CSI。逐项确认素材清单；脚本自动排除“标注/设计稿”开头的 PNG 和 BMFont 引用的纹理页，其他截图/废图仍需主动排除。BMFont 的 FNT 与纹理保持独立。
3. 逐个文字核对设计稿和标注的字形样式：斜体倾角、阴影色与偏移、描边、颜色、对齐。斜体用 `italic`（项目惯例 7–10°），阴影/描边用 `shadow`/`outline`，写进布局 JSON，不能只填文字、字号和颜色。渐变、多色、字间距等生成器不支持的效果列入交付说明。
4. 把测量结果写成布局 JSON，使用 `cocos_ui.py build` 生成 CSD。格式见 [references/layout.md](references/layout.md)。布局和绑定对应表随产物保留；已有 CSD 被用户手改后，先读取修改，再做局部调整，不能从旧 JSON 整页覆盖。
5. 使用 `scripts/pack_atlas.py` 按 CSI 本地生成 PNG/plist，并自动逐像素回读校验。Cocos Studio 自身也可从 CSI 导出图集；离线打包布局不承诺与编辑器相同。多页时按帧索引更新引用，不能继续把所有帧指向第一页。
6. 使用 `cocos_ui.py check` 检查最终 CSD，使用 `preview` 从最终 XML 生成离线预览；不要只渲染过期布局 JSON。

模型负责新设计稿的视觉判断、首次布局与项目语义映射。素材扫描、XML 生成、图集装箱、预览与校验交给脚本，只读取简短结果和必要图片，避免大段 XML/二进制内容进入对话。

## 真实兼容性与交付

- 编辑器拒绝导入或只提示解析失败时，使用 [cocos-editor-diagnostics](../cocos-editor-diagnostics/SKILL.md) 的本地/Windows 只读脚本取得实际异常链，再定位修改；不要靠资源存在或 XML 能解析来判定编辑器已恢复。

- 基础生成器覆盖 Node、Panel、Sprite、ImageView、Button、Text、TextBMFont 和 LoadingBar。复杂列表、嵌套 CSD、动画和项目自定义控件从工程样板复制对应结构，保留语义；不要为迁就脚本降级为图片。
- 区分编辑器格式与运行时 API。当前 sohoojs 使用的 `3.10.0.0` CSD 不写 `BarEnabled`；关闭滚动条在加载后调用 `setScrollBarEnabled(false)`。公共脚本的生成和校验均会拒绝该属性，不能因引擎支持就把它当作编辑器属性。
- ScrollView 的 `InnerNodeSize.Width/Height` 必须写整数字符串（如 `436`），不能复用 `Size.X/Y` 的浮点格式（如 `436.0000`）。Windows 编辑器会因此反序列化失败；公共 `check` 会拦截这一错误。
- 核对位置、字号、图标可见边缘、按钮热区、九宫格和不同宽高比。离线预览只作初筛；不支持的效果会明确报错，应改用编辑器或引擎截图。
- 可用 Cocos Studio 时实际打开、保存、导出，检查可编辑性和缺图，再用目标引擎核对画面与关键交互。不可用时明确列为待验证，不能把 XML/像素检查称为编辑器或 native/H5 兼容已通过。
- 接入代码若从模板 Text 新建或复制文字（列表行、滚动内容），要同时复制 `getRotationX/Y`（斜体）以及描边、阴影，否则运行时会丢掉 CSD 里的样式。
- 交付 CSD、CSI、布局参数、绑定对应表、必要散图/字体、图集与预览。区分编辑源资源目录和运行时导出目录；不要把离线试包直接混进正式发布流程。
- 新建目录制作首版；脚本默认拒绝覆盖，确认是本轮可重建产物后才使用 `--force`。不自动暂存、提交、打业务 bundle 或发布。
