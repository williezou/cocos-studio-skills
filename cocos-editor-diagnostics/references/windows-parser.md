# Windows 编辑器数据解析的有效路径

## 已验证环境与边界

2026-11-06 核对过的 Windows 编辑器位于 `C:\Cocos\Cocos Studio\CocosStudio.exe`，资源根示例为 `E:\willie_workspace\sohooccs\cocosstudio`。这些是历史环境值，脚本每次检查目标 DLL，并在报告中返回文件版本、进程位数和字段类型。

Cocos Studio 这一套程序集需要 **32 位 Windows PowerShell**：

```text
C:\Windows\SysWOW64\WindowsPowerShell\v1.0\powershell.exe
```

默认 64 位 PowerShell 加载混合程序集会报 `BadImageFormatException`，或 `GetTypes` 报 `ReflectionTypeLoadException`。这类错误不是 CSD 解析结果。脚本直接使用 32 位进程，并保留无法加载类型的警告。

## 解析器与错误证据

模型 DLL 为 `CocoStudio.Model.dll`，项目/序列化支持 DLL 为 `CocoStudio.Projects.dll`，均通过 `Assembly.LoadFrom` 从实际编辑器安装目录加载。数据解析使用：

```text
MonoDevelop.Core.Serialization.DataContext
MonoDevelop.Core.Serialization.XmlDataSerializer
CocoStudio.Model.DataModel.GameFileData
```

普通 .NET `System.Xml.Serialization.XmlSerializer` 不适用：`ExtendedProperties` 是 `IDictionary`，会在创建序列化器时失败，还没读 CSD，不能将其误报成文件错误。

不要实例化 `CocosFileFormat` 或调用 `AddinManager.Initialize` 来绕开环境问题。前者的静态初始化依赖已经启动的插件引擎，会报 `Add-in engine not initialized`；后者可能写插件注册表。独立诊断只使用数据模型，不创建视图模型或引擎节点。

只向 `DataContext` 注册 `BaseObjectData` 的公开派生数据类，不把 Model DLL 的所有辅助类都注册进去。脚本向 `GameFileData` 提供 `/GameFile/Content/Content` 这一层的 XML，使用 `SelectSingleNode`，不尝试给 XML 的只读 `Name` 属性赋值。捕获整个 `InnerException` 链，不只输出 PowerShell 的“调用 Deserialize 时发生异常”。解析返回 null 或 `ObjectData` 缺失时明确标为不完整，不能再调用 null 对象的 `GetType()` 产生二次错误。

## 此次明确定位的错误

原始异常链沿着主弹窗节点一直指向：

```text
Could not set property 'InnerNodeSize' in type 'ScrollViewObjectData'
Could not set property 'Width' in type 'SizeValue'
输入字符串的格式不正确。
```

`InnerNodeSize.Width/Height` 的编辑器类型是 `System.Int32`。生成代码把普通 `Size.X/Y` 的格式直接复制了过来：

```xml
<!-- 错误：XML 本身合法，但编辑器整数解析会失败 -->
<InnerNodeSize Width="436.0000" Height="225.0000" />
<!-- 正确 -->
<InnerNodeSize Width="436" Height="225" />
```

普通 `Size.X/Y` 可以保留浮点格式。修复时只改对应 `InnerNodeSize`，不要全局替换所有小数字符串；内容尺寸需要取整时向上取整。

`BarEnabled` 不在这台编辑器的 ScrollView 数据模型里，项目也不向 CSD 写入它；滚动条用运行时代码 `setScrollBarEnabled(false)` 关闭。**这个兼容性差异本身不是此次整数解析异常的证据**，不能把“字段不存在”直接等同于“它导致导入失败”。

## 日志、传输与复用

此次没有定位到可用的编辑器错误日志文件，因此脚本只搜索编辑器安装目录、`.Cocos` 及明确提供的编辑器日志根；限深度/数量，只读最近两份尾部。可用 `--log-root` 追加实际日志目录，不扫描整盘或无关应用。

调用参数通过 JSON/Base64 传入，SSH 不经过本地 shell 拼接；用短的 `-EncodedCommand` 引导程序从标准输入读取完整脚本，避免 Windows 约 8KB 命令行长度限制。报告通过 UTF-8 JSON/Base64 标记返回，避免中文被 Windows 代码页和 PowerShell CLIXML 错误流破坏。生产脚本永久保存在 skill 目录，不依赖 `/tmp`。

`--self-test` 在独立进程内用真实 `SizeValue.Width` 类型验证 `436` 可读、`436.0000` 被拒绝。输入文件含 ScrollView 时，还会深拷贝第一份文档，仅在内存中注入错误 Width，再用同一个解析器确认被拒绝并输出异常链；不改磁盘文件，也不代表主界面 GUI 导入已通过。若需要已知正常文件对照，追加一个当前可打开的 CSD，例如 `FishingRodCell.csd`。
