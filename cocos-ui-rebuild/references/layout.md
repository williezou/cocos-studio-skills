# 布局参数与控件语义

基础格式见 [../assets/layout-example.json](../assets/layout-example.json)。根字段为 `name`、`version`、`canvas`、`nodes`，可选 `root_type=Scene/Node`。可额外记录源代码位置、测量原点、状态和推定项；生成器只使用建图字段。

每个节点：

| 字段 | 含义 |
| --- | --- |
| name / type | 节点名和 node/panel/sprite/image/button/text/bmfont/loadingbar |
| rect | [左,上,宽,高]，父内容坐标，Y 向下，允许负位置 |
| anchor | [ax,ay]，Cocos 锚点，Y 向上，默认 [0.5,0.5] |
| resource | {"path":"完整帧名","plist":"图集路径"}；独立图片不填 plist |
| text / font / font_size | 文字、资源根下的字体路径、字号；bmfont 的 font 指向 FNT |
| color | [R,G,B,A]，默认全 255 |
| align | text 的水平对齐 left/center/right，默认 center |
| italic | text 的斜体倾角（度），写成单边 `RotationSkewX`，正值顶部右倾；项目常用 7–10，需在 ±45 内 |
| shadow | text 阴影 {"color":"#012e81" 或 [R,G,B,A],"offset":[x,y]}，offset 为 Cocos 坐标（Y 向上），默认 [2,-2] |
| outline | text 描边 {"color":…,"size":2} |
| touch / visible | 触摸/初始可见性；Button 默认带触摸 |
| scale9 | [左固定边,右固定边,上固定边,下固定边]，原图像素，仅 image/button |
| percent | LoadingBar 的 0–100 进度值，默认 100 |
| attrs | 额外 XML 属性，如 HorizontalEdge、VerticalEdge、PositionPercentXEnabled、ClipAble |
| children | 子节点数组 |
| clone | {"csd":"源 CSD 相对路径","node":"唯一节点名"}，替代 type/rect，从真实工程复制静态控件 |

clone 不用于带时间轴的控件；生成器会为生成树统一分配 Tag/ActionTag，不迁移原动画轨道。复杂结构需要同时迁移时间轴时直接操作对应 CSD，并校验关联。

`attrs` 只接受目标编辑器支持的属性。当前 `3.10.0.0` 格式禁止 `BarEnabled`，生成和 `check` 都会报错；关闭滚动条应在代码中调用 `setScrollBarEnabled(false)`。该规则不代表已经验证 ScrollView 的全部编辑器兼容性。

ScrollView 从工程样板复制时，`Size.X/Y` 可以使用浮点格式；`InnerNodeSize.Width/Height` 是编辑器整数类型，必须写成 `Width="436" Height="225"`，不能写 `436.0000`。像素尺寸需要取整时向上取整，不能直接把 `Size` 的字符串复制给 `InnerNodeSize`。公共 `check` 会拒绝小数、负数或缺失的内层尺寸字段。

常规控件的未缩放尺寸 W/H、父尺寸 PW/PH、设计左上角 L/T、锚点 ax/ay：

```text
Position.X = L + ax * W
Position.Y = PH - T - (1-ay) * H
LeftMargin = L
RightMargin = PW-L-W
TopMargin = T
BottomMargin = PH-T-H
```

Sprite 与 BMFont 保持原始内容尺寸，通过 Scale 达到目标矩形；普通控件 Scale=1、Size 为设计尺寸。原图透明边距参与锚点，不能改用裁边后尺寸。Sprite 的子节点坐标以其原始内容尺寸计算，复杂缩放分组优先包一层 Node。

四边吸附用 HorizontalEdge/VerticalEdge，中心组用 PositionPercentX/YEnabled；父容器需要有真实尺寸。百分比尺寸同时核对工程样板的 Enable/Enabled 属性与 PreSize。零尺寸 Node 适合挂模型，不适合当百分比布局容器。

## 结合已有代码做选择

1. 从现有创建函数与刷新函数列出动态字段，确认哪些控件会替换图片、改字符串、裁进度或反复生成 cell。
2. 读取事件绑定约定。已有 `m_` 名称和自定义类优先复用；纯代码控件建立“新节点名 → 原变量/字段/处理函数”对应表，不能声称推导名就是已有名。
3. 模型、Spine、头像、富文本等需要挂点与项目现有创建流程。不要把设计稿中的示例鱼、头像或模型烘焙进图片。
4. 动态文字用 Text；已有 FNT 用 TextBMFont 并验证所有示例字符存在。设计给出的字图继续用图片，业务替换品质字图时保留独立节点。
5. Button 区分热区、视觉底图和子文字；仅有正常态时可以先复用正常图，记录按下/禁用状态仍待编辑器或接入逻辑完善。脚本当前默认复用正常图。
6. 依据实际图像确定九宫格边距；没有拉伸需求时保留原始尺寸。列表/滚动/进度须保持控件语义和内层尺寸；高级结构从工程样板复制，基础脚本不覆盖时不要硬转成 Sprite。

7. 设计稿中的斜体、阴影、描边属于需要还原的样式，必须写进 `italic`/`shadow`/`outline`。sohoojs 现有 CSD（如 `fishing/addr__remote/rod/` 下用户手调过的两份）的斜体都是在 Cocos Studio 里只设 `RotationSkewX`，Studio、native 和 H5 都按斜切渲染，这就是工程的斜体做法。标注里写了“阴影 #xxxxxx”时同时启用阴影；只写偏移不启用（`ShadowEnabled` 缺省）在引擎里不会显示。

单边 RotationSkewX 在 native 上克隆该控件或其祖先会撞 CCNode 断言，`check` 会列出这些节点；接入代码不要对它们用 clone，改为新建控件并复制 `getRotationX/Y`。需要平面旋转时两值相等。渐变字、多色字、字间距等生成器不支持的效果需说明并在编辑器/运行时确认。

## 动态列表与嵌套模板

动态 ScrollView 的正式 CSD 只定义视口与固定装饰，数据项交给运行时代码。重复的行或列做成一个独立 CSD，内层初始尺寸取视口大小，再由代码按数据更新。需要在编辑器里嵌入模板时，用一个 ProjectNode 引用独立 CSD，并把这个节点直接作为首项复用。检查正式 CSD 和布局参数，避免把设计稿中的示例行或占位容器带进运行时再删除。需要展示多项效果时，只在离线预览的临时副本展开示例。

### 成员命名

sohoojs 的 CSD 加载器会为 `m_` 节点建立成员引用。代码需要访问的容器、重复行与行内字段都按此命名，不能只给最外层加前缀。例如：

```text
m_singleAttrs
  m_row1
    m_txtName
    m_txtValue
  m_row2
    m_txtName
    m_txtValue
```

接入直接使用 `this.m_singleAttrs.m_row1.m_txtName`；循环用 `group['m_row' + i]`。不同父节点下允许重复 `m_txtName`，访问时保留父子路径，避免依赖加载器在页面对象上覆盖的同名成员。不再递归查找、二次绑定，或赋值 `row.txtName = ...` 这样的别名。

布局 JSON 的 `name` 写最终名称，Python `build` 原样保留层级和名称，不自动给全部节点加前缀；纯装饰节点不强制加 `m_`。已有 UI 名称属于接口，改名时同步 CSD、布局参数、绑定对应表与代码引用，并重新导出对应 CSB 后验证。不要全局替换其他模板中的同名节点，也不要用运行时重命名掩盖旧 CSB。

## 手工修改后

用户在 Cocos Studio 的修改以当前 CSD 为准。先 diff 当前 XML 与上次产物，把需要继续脚本重建的修改同步到布局参数；复杂手工修改无法无损回写时直接保留 XML 并局部编辑。不得用旧 JSON 覆盖用户调整。
