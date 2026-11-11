#!/usr/bin/env python3
"""只读检查 CSD；可通过 SSH 使用 Windows Cocos Studio 自身的数据模型排查。"""
import argparse
import base64
import json
import ntpath
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

MARKER = "CSD_DIAGNOSTICS_JSON:"


def relative_name(value):
    name = value.replace("\\", "/")
    path = PurePosixPath(name)
    if not name or path.is_absolute() or ":" in name or ".." in path.parts:
        raise ValueError("需要资源根目录内的相对路径：" + value)
    return path.as_posix()


def project_entries(path):
    entries = set()

    def walk(node, folder):
        if node.tag == "Folder":
            folder = folder / node.get("Name", "")
        if node.tag == "Project":
            entries.add((folder / node.get("Name", "")).as_posix())
        for child in node:
            walk(child, folder)

    walk(ET.parse(path).getroot(), PurePosixPath())
    return entries


def local_report(root, files, project=None, max_files=64):
    root = Path(root).resolve()
    registered = project_entries(project) if project else None
    queue = [relative_name(f) for f in files]
    visited = set()
    results = []
    while queue and len(visited) < max_files:
        name = queue.pop(0)
        if name in visited:
            continue
        visited.add(name)
        result = {"file": name, "issues": [], "references": []}
        results.append(result)
        path = root / name
        if not path.is_file():
            result["issues"].append({"severity": "error", "code": "missing_file", "path": name})
            continue
        try:
            tree = ET.parse(path).getroot()
        except ET.ParseError as error:
            result["issues"].append({"severity": "error", "code": "xml_syntax",
                                     "message": str(error), "line": error.position[0]})
            continue
        group = tree.find("PropertyGroup")
        result["version"] = group.get("Version") if group is not None else None
        action_tags = set()
        for node in tree.iter():
            node_name = node.get("Name")
            tag = node.get("ActionTag")
            if tag:
                if tag in action_tags:
                    result["issues"].append({"severity": "error", "code": "duplicate_action_tag",
                                             "node": node_name, "value": tag})
                action_tags.add(tag)
            if node.get("ctype") == "ScrollViewObjectData":
                inner = node.find("InnerNodeSize")
                if inner is not None:
                    for key in ("Width", "Height"):
                        value = inner.get(key, "")
                        if re.fullmatch(r"[0-9]+", value) is None:
                            result["issues"].append({"severity": "error", "code": "inner_size_integer",
                                "node": node_name, "field": "InnerNodeSize." + key, "value": value,
                                "message": "编辑器整数类型不能读取 436.0000 这样的浮点字符串"})
                if result["version"] == "3.10.0.0" and "BarEnabled" in node.attrib:
                    result["issues"].append({"severity": "warning", "code": "unsupported_editor_attribute",
                        "node": node_name, "field": "BarEnabled",
                        "message": "已核对的编辑器数据模型没有该属性；用代码 setScrollBarEnabled(false)，不能据此认定解析失败根因"})
            if node.get("ctype") != "ProjectNodeObjectData":
                continue
            data = node.find("FileData")
            try:
                ref = relative_name(data.get("Path", "") if data is not None else "")
            except ValueError as error:
                result["issues"].append({"severity": "error", "code": "invalid_reference",
                                         "node": node_name, "message": str(error)})
                continue
            exists = (root / ref).is_file()
            info = {"node": node_name, "path": ref, "exists": exists}
            if registered is not None:
                info["registered_in_supplied_project"] = ref in registered
                if exists and ref not in registered:
                    result["issues"].append({"severity": "warning", "code": "project_registration",
                        "path": ref, "message": "所提供 .ccs 未登记；不能代替核对 Windows 当前打开的工程"})
            result["references"].append(info)
            if exists:
                queue.append(ref)
            else:
                result["issues"].append({"severity": "error", "code": "missing_reference", "path": ref})
    return {"mode": "local", "root": str(root), "files": results, "truncated": bool(queue),
            "validation": "XML、已知字段格式和嵌套引用检查；不证明编辑器可打开或缺图已全部排除"}


def decode_remote(stdout, stderr=b""):
    text = stdout.decode("utf-8-sig", "replace")
    for line in reversed(text.splitlines()):
        if line.startswith(MARKER):
            return json.loads(base64.b64decode(line[len(MARKER):]).decode("utf-8-sig"))
    try:
        detail = stderr.decode("utf-8")
    except UnicodeDecodeError:
        detail = stderr.decode("gb18030", "replace")
    raise RuntimeError("Windows 未返回诊断报告；这属于诊断工具/传输失败，不能归因于 CSD。\n" + detail[-1800:])


def ssh_command(target, port, powershell):
    if not re.fullmatch(r"(?:[\w.-]+@)?[\w.-]+", target) or target.startswith("-"):
        raise ValueError("SSH 目标只能是用户名@主机或 SSH 别名")
    if not 1 <= port <= 65535 or any(c in powershell for c in '\r\n"'):
        raise ValueError("无效 SSH 端口或 PowerShell 路径")
    bootstrap = ("$ProgressPreference='SilentlyContinue';"
        "[Console]::InputEncoding=[Text.UTF8Encoding]::new($false);"
        "[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false);"
        "$body=[Console]::In.ReadToEnd();& ([ScriptBlock]::Create($body))")
    encoded = base64.b64encode(bootstrap.encode("utf-16le")).decode("ascii")
    command = '"' + powershell + '" -NoLogo -NoProfile -NonInteractive -EncodedCommand ' + encoded
    return ["ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=6", "-p", str(port), target, command]


def windows_report(args):
    config = {"Root": args.root, "Files": [relative_name(f) for f in args.file],
              "EditorDir": args.editor_dir, "Logs": args.logs, "LogRoots": args.log_root,
              "SelfTest": args.self_test}
    if not ntpath.isabs(args.root) or not ntpath.isabs(args.editor_dir):
        raise ValueError("Windows 资源根和编辑器目录必须是绝对路径")
    payload = base64.b64encode(json.dumps(config, ensure_ascii=False).encode("utf-8")).decode("ascii")
    source = Path(__file__).with_name("editor_probe.ps1").read_text(encoding="utf-8")
    script = "$ConfigurationBase64='" + payload + "'\n" + source
    command = ssh_command(args.ssh, args.port, args.powershell)
    result = subprocess.run(command, input=script.encode("utf-8"), stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=args.timeout)
    report = decode_remote(result.stdout, result.stderr)
    if result.returncode:
        report["transport_exit_code"] = result.returncode
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="完整 JSON 报告的本地保存路径")
    commands = parser.add_subparsers(dest="mode", required=True)
    local = commands.add_parser("local", help="离线检查，不需要第三方 Python 包")
    local.add_argument("--root", type=Path, required=True, help="cocosstudio 资源根目录")
    local.add_argument("--file", action="append", required=True, help="CSD 相对路径，可重复")
    local.add_argument("--project", type=Path, help="可选 .ccs 工程清单")
    windows = commands.add_parser("windows", help="SSH 只读调用 Windows 编辑器模型")
    windows.add_argument("--ssh", required=True)
    windows.add_argument("--root", required=True)
    windows.add_argument("--file", action="append", default=[])
    windows.add_argument("--editor-dir", default=r"C:\Cocos\Cocos Studio")
    windows.add_argument("--powershell", default=r"C:\Windows\SysWOW64\WindowsPowerShell\v1.0\powershell.exe")
    windows.add_argument("--port", type=int, default=22)
    windows.add_argument("--timeout", type=int, default=45)
    windows.add_argument("--logs", action="store_true", help="限深度、数量查找编辑器日志并取最近两份尾部")
    windows.add_argument("--log-root", action="append", default=[], help="追加明确的编辑器日志目录")
    windows.add_argument("--self-test", action="store_true", help="在内存中验证实际编辑器整数类型的正反例")
    args = parser.parse_args()
    try:
        if args.mode == "windows" and not (args.file or args.logs or args.self_test):
            parser.error("windows 模式需指定 --file、--logs 或 --self-test")
        report = local_report(args.root, args.file, args.project) if args.mode == "local" else windows_report(args)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(json.dumps({"mode": args.mode, "harness_error": str(error)}, ensure_ascii=False, indent=2))
        return 2
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report.get("harness_error") or report.get("transport_exit_code"):
        return 2
    errors = any(issue.get("severity") == "error" for f in report.get("files", []) for issue in f.get("issues", []))
    errors = errors or any(f.get("status") in ("parse_error", "xml_error", "missing_file") for f in report.get("files", []))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
