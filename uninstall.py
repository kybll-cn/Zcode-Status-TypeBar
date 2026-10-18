#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Zcode-Status-TypeBar —— 卸载器（Windows）。

默认行为：
  1. 从 app.asar 的主进程入口移除插件注入行（会同步修正 asar 头部）；
  2. 从 ZCode CLI 配置中移除 MCP server 注册；
  3. 删除插件目录。

可选：
  --restore-backup   用安装时生成的 app.asar.zusage-backup-<版本> 还原客户端
                     （仅在客户端版本未升级时可用；升级后请用默认的“移除注入”模式）
  --keep-files       保留插件目录（只移除注入和 MCP 注册）
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
from pathlib import Path

PLUGIN_NAME = "Zcode-Status-TypeBar"
INJECT_MARKER = "[zusage] load failed"
INJECT_RE = re.compile(
    r'(?m)^[ \t]*;?import\("file:///[^"\r\n]*inject-main\.cjs"\)'
    r'\.then\(\(\) => null, \(e\) => console\.error\("\[zusage\] load failed", e\)\);[ \t]*\r?\n?'
)


def say(msg: str = "") -> None:
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        print(msg.encode("utf-8", "replace").decode("utf-8", "replace"), flush=True)


def fail(msg: str) -> None:
    say("\n[错误] " + msg)
    raise SystemExit(1)


# ------------------------------------------------------------------ asar 读写
def parse_asar(fh):
    raw = fh.read(16)
    if len(raw) != 16:
        raise ValueError("文件太小，不是有效的 asar")
    magic, b, c, d = struct.unpack("<IIII", raw)
    if magic != 4 or d <= 0 or b != d + 8 or c != d + 4:
        raise ValueError("不是有效的 asar 头部")
    header = json.loads(fh.read(d))
    return header, 8 + b


def iter_entries(header):
    def walk(node, prefix):
        for name, entry in node.get("files", {}).items():
            full = prefix + "/" + name if prefix else name
            if isinstance(entry, dict) and "files" in entry:
                yield from walk(entry, full)
            else:
                yield full, entry
    yield from walk(header, "")


def get_entry(header, path):
    node = header
    for seg in path.replace("\\", "/").strip("/").split("/"):
        node = node.get("files", {}).get(seg)
        if node is None:
            return None
    return node


def read_entry(fh, data_start, entry):
    fh.seek(data_start + int(entry["offset"]))
    return fh.read(int(entry["size"]))


def make_integrity(data, block_size=4 * 1024 * 1024):
    blocks = [hashlib.sha256(data[i:i + block_size]).hexdigest()
              for i in range(0, len(data), block_size)]
    return {"algorithm": "SHA256", "hash": hashlib.sha256(data).hexdigest(),
            "blockSize": block_size, "blocks": blocks}


def repack_asar(src, dst, replacements):
    with open(src, "rb") as fin:
        header, data_start = parse_asar(fin)
        items = []
        for full, entry in iter_entries(header):
            if entry.get("unpacked") or "link" in entry or "offset" not in entry:
                items.append((full, entry, None, 0, None))
                continue
            items.append((full, entry, int(entry["offset"]), int(entry["size"]),
                          replacements.get(full)))
        cursor = 0
        for full, entry, old_off, old_size, new_data in items:
            if old_off is None:
                continue
            size = len(new_data) if new_data is not None else old_size
            entry["size"] = size
            entry["offset"] = str(cursor)
            if new_data is not None and "integrity" in entry:
                entry["integrity"] = make_integrity(new_data)
            cursor += size
        header_bytes = json.dumps(header, ensure_ascii=False,
                                  separators=(",", ":")).encode("utf-8")
        prefix = struct.pack("<IIII", 4, len(header_bytes) + 8,
                             len(header_bytes) + 4, len(header_bytes))
        with open(dst, "wb") as fout:
            fout.write(prefix)
            fout.write(header_bytes)
            for full, entry, old_off, old_size, new_data in items:
                if old_off is None:
                    continue
                if new_data is not None:
                    fout.write(new_data)
                    continue
                fin.seek(data_start + old_off)
                remaining = old_size
                while remaining:
                    chunk = fin.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise ValueError(f"读取 asar 内容失败: {full}")
                    fout.write(chunk)
                    remaining -= len(chunk)
            fout.flush()
            os.fsync(fout.fileno())


def find_entry_path(asar_path):
    with open(asar_path, "rb") as fh:
        header, data_start = parse_asar(fh)
        pkg = get_entry(header, "package.json")
        if pkg and "offset" in pkg:
            try:
                obj = json.loads(read_entry(fh, data_start, pkg).decode("utf-8"))
                main = str(obj.get("main") or "out/main/index.js").replace("\\", "/")
                if main.startswith("./"):
                    main = main[2:]
                return main.lstrip("/")
            except Exception:
                pass
    return "out/main/index.js"


def strip_injection(asar_path):
    entry_path = find_entry_path(asar_path)
    with open(asar_path, "rb") as fh:
        header, data_start = parse_asar(fh)
        entry = get_entry(header, entry_path)
        if not entry or "offset" not in entry:
            raise ValueError(f"找不到入口文件: {entry_path}")
        text = read_entry(fh, data_start, entry).decode("utf-8")
        if INJECT_MARKER not in text:
            return False, entry_path
        cleaned = INJECT_RE.sub("", text).rstrip()
        if INJECT_MARKER in cleaned:
            raise ValueError("检测到多段注入且无法安全移除，请使用 --restore-backup")
        data = (cleaned + "\n").encode("utf-8")
        replacements = {entry_path: data}

    tmp = asar_path.with_name(asar_path.name + ".zusage-tmp")
    try:
        repack_asar(asar_path, tmp, replacements)
        with open(tmp, "rb") as fh:
            header, data_start = parse_asar(fh)
            entry = get_entry(header, entry_path)
            content = read_entry(fh, data_start, entry)
            if INJECT_MARKER in content.decode("utf-8"):
                raise ValueError("临时 asar 校验失败：注入行仍在")
            if "integrity" in entry:
                if hashlib.sha256(content).hexdigest() != entry["integrity"]["hash"]:
                    raise ValueError("临时 asar 校验失败：SHA256 不一致")
        os.replace(tmp, asar_path)
    except Exception:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    return True, entry_path


def is_zcode_running():
    if os.name != "nt":
        return False
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq ZCode.exe", "/NH"],
                             capture_output=True, text=True, errors="ignore",
                             timeout=10).stdout
        return "ZCode.exe" in out
    except Exception:
        return False


def find_asar(explicit, plugin_dir):
    candidates = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    cfg = plugin_dir / "config.json"
    if cfg.exists():
        try:
            p = json.loads(cfg.read_text(encoding="utf-8-sig")).get("asar_path")
            if p:
                candidates.append(Path(p))
        except Exception:
            pass
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(Path(local) / "Programs" / "ZCode" / "resources" / "app.asar")
        candidates.append(Path(local) / "ZCode" / "resources" / "app.asar")
    for env in ("PROGRAMFILES", "PROGRAMFILES(X86)"):
        base = os.environ.get(env)
        if base:
            candidates.append(Path(base) / "ZCode" / "resources" / "app.asar")
    for c in candidates:
        if c.is_file():
            return c.resolve()
    fail("没有找到 app.asar，请用 --asar 指定路径。")


def unregister_mcp(config_path, dry_run=False):
    if not config_path.exists():
        return False
    try:
        cfg = json.loads(config_path.read_text(encoding="utf-8-sig"))
    except Exception as e:
        say("  [跳过] 无法解析 " + str(config_path) + ": " + str(e))
        return False
    servers = cfg.get("mcp", {}).get("servers", {}) if isinstance(cfg, dict) else {}
    if not isinstance(servers, dict) or PLUGIN_NAME not in servers:
        return False
    if dry_run:
        return True
    backup = config_path.with_name(config_path.name + ".zusage.bak")
    if not backup.exists():
        shutil.copy2(config_path, backup)
    del servers[PLUGIN_NAME]
    tmp = config_path.with_name(config_path.name + ".tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, config_path)
    return True


def find_backup(asar_path):
    backups = sorted(asar_path.parent.glob(asar_path.name + ".zusage-backup-*"))
    backups = [b for b in backups if b.is_file()]
    return backups[-1] if backups else None


def main():
    parser = argparse.ArgumentParser(description="卸载 Zcode-Status-TypeBar（Windows）。")
    parser.add_argument("--asar", help="ZCode 的 app.asar 路径（默认自动查找）")
    parser.add_argument("--dest", help="插件安装目录（默认 %%USERPROFILE%%\\.zcode\\"
                                      + PLUGIN_NAME + "）")
    parser.add_argument("--mcp-config", help="ZCode CLI 配置文件路径（调试用）")
    parser.add_argument("--keep-files", action="store_true", help="保留插件目录")
    parser.add_argument("--restore-backup", action="store_true",
                        help="用安装时的备份还原 app.asar（不要跨客户端版本使用）")
    parser.add_argument("--force", action="store_true", help="跳过 ZCode 进程检查")
    parser.add_argument("--dry-run", action="store_true", help="只显示将执行的操作")
    args = parser.parse_args()

    dest = (Path(args.dest).expanduser() if args.dest
            else Path.home() / ".zcode" / PLUGIN_NAME).resolve()
    asar = find_asar(args.asar, dest)
    say("Zcode-Status-TypeBar 卸载器")
    say("  app.asar: " + str(asar))

    if is_zcode_running() and not args.force and not args.dry_run:
        fail("检测到 ZCode 正在运行。请完全退出 ZCode（包括托盘图标）后重试。")

    try:
        if args.restore_backup:
            backup = find_backup(asar)
            if not backup:
                fail("没有找到 app.asar.zusage-backup-* 备份。")
            say("将用备份还原: " + str(backup))
            if not args.dry_run:
                shutil.copy2(backup, asar)
            say("[1/3] 已还原 app.asar")
        else:
            if args.dry_run:
                present = False
                with open(asar, "rb") as fh:
                    header, data_start = parse_asar(fh)
                    entry = get_entry(header, find_entry_path(asar))
                    if entry and "offset" in entry:
                        present = INJECT_MARKER in read_entry(fh, data_start, entry).decode("utf-8")
                say("[1/3] 注入行: " + ("存在，将移除" if present else "不存在"))
            else:
                removed, entry_path = strip_injection(asar)
                say("[1/3] " + ("已移除注入（入口 " + entry_path + "）"
                                if removed else "未发现注入，跳过"))
    except PermissionError as e:
        fail(f"没有权限写入 app.asar: {e}\n请关闭 ZCode 后重试。")
    except Exception as e:
        fail(f"处理 app.asar 失败: {e}")

    mcp_cfg = (Path(args.mcp_config).expanduser() if args.mcp_config
               else Path.home() / ".zcode" / "cli" / "config.json")
    removed = unregister_mcp(mcp_cfg, dry_run=args.dry_run)
    if args.dry_run:
        say("[2/3] " + ("MCP 注册存在，将移除" if removed else "未发现 MCP 注册"))
    else:
        say("[2/3] " + ("已移除 MCP 注册" if removed else "未发现 MCP 注册，跳过"))

    if args.keep_files:
        say("[3/3] 保留插件目录: " + str(dest))
    elif args.dry_run:
        say("[3/3] 将删除插件目录: " + str(dest))
    else:
        try:
            os.chdir(Path.home())   # 若当前目录就在插件目录内，先离开，避免 Windows 无法删除
            if dest.exists():
                shutil.rmtree(dest)
            say("[3/3] 已删除插件目录: " + str(dest))
        except Exception as e:
            say("[3/3] [警告] 删除插件目录失败: " + str(e))
            say("      请手动删除: " + str(dest))

    say("")
    say("卸载完成。请重新启动 ZCode。")
    if args.restore_backup:
        say("注意：如果 ZCode 客户端已升级，旧备份可能导致版本不匹配；")
        say("      遇到启动异常请重新安装 ZCode 或重新运行安装器。")


def _use_console_encoding() -> None:
    """把 stdout/stderr 对齐到控制台当前编码（同 install.py）。

    强制 utf-8 会在中文 Windows 的 cmd（GBK/936）里变成乱码 —— 一键卸载脚本
    双击运行时正是这种环境。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            encoding = (stream.encoding or "").lower()
            if "utf" in encoding:
                stream.reconfigure(encoding="utf-8", errors="replace")
            else:
                stream.reconfigure(encoding=encoding or None, errors="replace")
        except Exception:
            pass


if __name__ == "__main__":
    _use_console_encoding()
    main()
