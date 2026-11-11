# cocos-studio-skills

两个用于 Cocos Studio（cocos2d-x 3.10 时代编辑器）工作流的 agent skill。

## cocos-editor-diagnostics

排查 CSD 导入、解析或打开失败：本地检查 XML 行号、ActionTag、嵌套引用与已知整数格式；需要 Windows 证据时通过 SSH 只读调用编辑器自带的 32 位数据模型与 MonoDevelop 解析器，拿到真实异常链再定位字段。

## cocos-ui-rebuild

根据 UI 散图和设计稿，本地生成可在 Cocos Studio 中编辑的 CSD、CSI 图集描述及 PNG/plist，并生成离线预览与资源检查（Python 3.10+ / Pillow）。

## 使用

两个目录即 skill 目录，可复制或软链到 `~/.codex/skills/`（Codex）或 `~/.claude/skills/`（Claude Code）等 skill 加载路径。`cocos-ui-rebuild/scripts` 依赖 Pillow：`pip install -r cocos-ui-rebuild/requirements.txt`。
