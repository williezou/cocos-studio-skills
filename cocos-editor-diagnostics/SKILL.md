---
name: cocos-editor-diagnostics
description: "排查 Cocos Studio 的 CSD 导入、解析或打开失败，检查修改差异和嵌套引用，读取 Windows 编辑器日志，并通过编辑器自带的 32 位数据模型与 MonoDevelop 解析器定位异常字段。用于编辑器拒绝 CSD 或没有清晰报错的情况；不负责美术重建或游戏运行时 UI 逻辑。"
---

# Cocos Studio 解析错误排查

先取得具体异常字段，再修改源文件。XML 能解析、资源文件存在、引擎能加载，均不能单独证明编辑器能够导入。

## 快速执行

脚本使用本地 Python 3 标准库，无需临时写 PowerShell 或安装 Python 依赖。文件路径相对于 `cocosstudio` 资源根，可重复传 `--file`；`--output` 放在子命令前，保存完整 JSON 报告。

先检查用户指出的文件和最近改动，不批量扫描整个项目：

```bash
python3 scripts/diagnose_csd.py --output /本地工作目录/csd-local.json local \
  --root /工程/cocosstudio \
  --file fishing/addr__remote/rod/FishingNewRod.csd
```

本地检查覆盖 XML 行号、ActionTag、嵌套 CSD 是否存在、已知整数格式。可传 `--project /工程/Sohooo.ccs` 检查该清单中的登记情况；本地清单可能落后于 Windows，不能据此认定远端缺依赖。

需要 Windows 证据时，一次 SSH 同时核对编辑器模型、读取指定文件和搜索有限范围的日志：

```bash
python3 scripts/diagnose_csd.py --output /本地工作目录/csd-windows.json windows \
  --ssh peter.dai@192.168.101.17 \
  --root 'E:\willie_workspace\sohooccs\cocosstudio' \
  --editor-dir 'C:\Cocos\Cocos Studio' \
  --file fishing/addr__remote/rod/FishingNewRod.csd \
  --file fishing/addr__remote/rod/FishingRodUpgradeSuccess.csd \
  --logs --self-test
```

以上机器、账号、路径是本项目已核对的示例，换环境时核对当前值，不视为额外操作授权。Windows 端仅从标准输入执行只读脚本，不上传脚本、修改工程、初始化插件注册表或启动/重启编辑器。SSH 使用现有密钥；不保存密码，不修改 SSH 配置。

## 判断报告

- `harness_error`、传输超时或 DLL 加载失败属于诊断工具/环境问题，不能当成 CSD 错误。优先核对目录与位数，不再逐个猜 DLL 或反复输出反射清单。
- `parse_error` 保留编辑器底层解析器的完整 `exception_chain`，先看最内层异常，再沿字段链定位，如 `ObjectData → Children → InnerNodeSize → Width`。
- `editor_type_conversion` 给出真实编辑器字段类型、节点名和原始值；可直接回到源 XML 做单点修正。
- `data_only_ok` 仅表示独立进程的数据模型解析成功；`data_only_incomplete` 表示未取得完整根对象。两者都不是 GUI 导入、资源登记、字体、渲染或 CSB 导出的验收。
- `logs` 为空只表示限定目录未找到匹配日志。此次决定性证据来自程序集的异常链，不是某个已知日志路径；不要编造固定日志位置或声称已读到日志。
- 模型里不存在的属性只报兼容性警告，不能自动当成根因；资源在磁盘上也不能证明已登记到当前编辑器工程。

若所有文件包括一份已知可打开的同类 CSD 都出现相同异常，先排查诊断环境；不要同时修改多处 XML。修复后运行同一命令对照，保持日志、调用参数和原始错误证据；要声称“编辑器已恢复”，仍需观察实际编辑器结果。

位数、异常链和此次踩坑细节见 [references/windows-parser.md](references/windows-parser.md)。工具回归可执行 `python3 scripts/test_diagnose_csd.py`。
