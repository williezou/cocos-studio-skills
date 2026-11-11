# 本地脚本流程

以下 `$SKILL` 表示本技能目录，`$PY` 表示已安装 Pillow 的 Python。不要固定使用某个临时虚拟环境路径；先检查当前环境。

```bash
python3 -m venv /可写目录/cocos-ui-venv
/可写目录/cocos-ui-venv/bin/python -m pip install Pillow
```

## 素材与 CSI

```bash
$PY "$SKILL/scripts/cocos_ui.py" inventory --input /input/slices --output /output/review
$PY "$SKILL/scripts/cocos_ui.py" csi --template /studio/ui/example/images.csi --resource-root /studio --directory ui/new-page/images --output /output/studio/ui/new-page/images.csi
```

联系表每页最多 48 张，数字索引对应 `inventory.json`；非 ASCII 文件名以 JSON 为准。输出目录置于输入目录外，避免将预览再次盘点为素材。

已测到切图大致位置时可用局部像素匹配辅助定位，降低反复人工推算的成本：

```bash
$PY "$SKILL/scripts/cocos_ui.py" match --design /input/design.png --slice /input/title.png --near 600 150 --radius 24 --scales 0.95 1 1.05
```

`near` 使用原始设计稿像素坐标。匹配只比较切图不透明核心，输出候选矩形与颜色误差；半透明图会拒绝，遮挡/字图叠加可导致误差较大。先查看对照图，再决定是否采用候选，不把误差当成最终验收评分。

CSI 继承样板的版本、ExportType、SortAlgorithm、PicturePadding、旋转/裁边和 MaxSize，只改 Name、ID 与图片清单。FNT 引用的纹理页不能放进普通图集，否则 BMFont 的页路径/字形坐标会失效。

CSI 的 `FilePathData.Path` 相对 `cocosstudio` 等资源根目录。CSD 图集引用的 `Plist` 写导出时的 `.plist` 路径；源工程中对应的是同名 `.csi`，不是把 `.csi` 写入 Plist 属性。散图保留原目录，方便编辑器读取和用户替换。

## 构建、检查和预览

```bash
$PY "$SKILL/scripts/cocos_ui.py" build --layout /output/Page.layout.json --resource-root /output/studio --resource-root /project/cocosstudio --output /output/studio/ui/new-page/Page.csd
$PY "$SKILL/scripts/cocos_ui.py" check --csd /output/studio/ui/new-page/Page.csd --resource-root /output/studio --resource-root /project/cocosstudio
$PY "$SKILL/scripts/cocos_ui.py" preview --csd /output/studio/ui/new-page/Page.csd --resource-root /output/studio --resource-root /project/cocosstudio --width 1624 --output /output/review/Page.png
$PY "$SKILL/scripts/cocos_ui.py" compare --design /input/design.png --crop 88 126 1624 750 --preview /output/review/Page.png --output /output/review/comparison
```

多个 resource-root 依次查找，适合新增文件在输出目录、公共资源仍在现有工程的情形。最终交付时仍需确保这些资源在目标工程里实际存在。

检查覆盖 XML 根结构、兄弟重名、ActionTag 冲突、有限数值、源路径大小写、CSI 帧成员、FNT 页纹理和九宫格范围。它验证的是源资源完整性，不验证真实导出 plist 的运行时加载。RotationSkewX/Y 不相等（单边斜切，美术常用来做斜体字）不算错误，结果里 `warnings` 列出这些节点：普通加载正常，但 native 克隆它们或其祖先会撞 CCNode 断言，接入代码时不要对这些节点用 clone。

预览器读取最终 XML，支持基础位置/正缩放、锚点、Sprite 翻转、九宫格、文本 FNT、普通 TTF（含描边、阴影）、无子节点控件的单边 RotationSkewX 斜切和矩形裁剪，以及百分比尺寸/位置和四边吸附的基础模拟。文字折行、RotationSkewY/平面旋转、带子节点的斜切、时间轴和其他节点类型需用编辑器或引擎验证；遇到已知不支持的结构报错，不静默丢掉节点。离线字体基线、采样、透明混合与真实引擎仍可能不同。

设计稿若包含黑边/红色标注，先明确有效画面矩形和逻辑画布原点。生成同尺寸的预览并做叠加对照；保留原始设计稿，不能把标注或示例背景当作新增 UI 资源。

## 本地图集

```bash
$PY "$SKILL/scripts/pack_atlas.py" --csi /output/studio/ui/new-page/images.csi --resource-root /project/cocosstudio --output /output/export-preview/ui/new-page
```

打包器实现不旋转的 MaxRects、透明裁边、完整帧名、format 2、2 的幂页面、1 像素边缘扩展和尺寸溢出拆页，继承 CSI 的上限/间隔/裁边设置。AllowRotation=True 时会拒绝，改用编辑器或按项目要求关闭旋转。单张过大报错，不缩小原图。可见 RGBA 从 PNG/plist 回读还原后逐像素校验，完全透明像素的 RGB 不比较。

输出 `images.png/plist` 和 `images.atlas.json`；多页输出 `images_0`、`images_1`。帧索引给出每帧真实页文件；多页必须同步更新 CSD 的 Plist。编辑器重导出后的装箱位置可以不同，只要帧名、源尺寸、偏移和引用正确。

## sohoojs 参考

源工程 `/Volumes/ExtremeSSD/workspace/yoyoohuyu/sohooccs/cocosstudio/`。本次已核对钓鱼样板 `fishing/addr__remote/seaview/SeaViewScene.csd` 与 `images.csi`：Version 3.10.0.0、设计尺寸 1334×750。它们只是参考，后续仍读取当前样板与项目指引。

已有结果页功能在 `src/model/fishing/ui/scene_fishing.js`：`_buildSuccess/_buildFail` 经 `_createResultUI` 把 `FishingResultSuccess.csb`/`FishingResultFail.csb` 加载到独立节点（成员不覆盖主页同名控件），按钮回调在该节点的 `_onButtonClicked`。鱼名/品质/重量/新纪录/奖励来自 ret，确认回 `_leaveResult`，提升装备到 `_openRodManage`，重试用 `_cast`，重试可用性由 `_setRetryEnabled`/`_refreshResultPoints` 管理；资源缺失走 `_buildResultFailure`。资源重建时按这些行为保留动态节点与控件，并同步 `_createResultUI` 里的必需节点和图集帧清单；代码位置和名称以当前实现为准。
