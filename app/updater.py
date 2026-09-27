#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自动更新

每次启动工具时，去下载站看一眼 manifest.json：
  · 线上版本比本地新  -> 下载 zip、校验 sha256、解压覆盖到工具目录
  · 一样 / 网络不通    -> 什么都不做（不会卡启动，最多等几秒）

下载站： https://mcdownload.bony-doorframe-shortly.top/manifest.json
换地址： 改环境变量 MC_UPDATE_URL；想关掉自动更新：MC_NO_UPDATE=1

更新时**绝不动**这些东西： .mc-tool.json（你的种子）、记录/、logs/、.build-cache/、runtime/
—— 所以更新只换程序，不碰配置和存档记录。

命令行用法：
  python3 app/updater.py            # 看一眼有没有新版本
  python3 app/updater.py --force    # 不管版本号，直接重装一遍
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile

try:
    import release
except ImportError:
    release = None

HERE = os.path.dirname(os.path.abspath(__file__))          # app/
ROOT = os.path.dirname(HERE)                               # 工具包根目录
VERSION_FILE = os.path.join(HERE, "VERSION")

BASE_URL = "https://mcdownload.bony-doorframe-shortly.top"
# 两个通道：稳定版所有人默认走这条；测试版是给"愿意帮忙试"的人用的
CHANNELS = {
    "stable": "/manifest.json",
    "beta": "/manifest-beta.json",
}
CHANNEL_NAMES = {"stable": "稳定版", "beta": "测试版"}
DEFAULT_CHANNEL = "stable"
TIMEOUT = 6                      # 秒：没网的时候最多卡这么久，然后当没事发生
# 只认这个域名。万一有人把 MC_UPDATE_URL 指到别处，下面的签名校验才是最后一道锁。
ALLOWED_HOSTS = ("mcdownload.bony-doorframe-shortly.top",)
# 没签名也要更新（只应该在自己调试的时候用）
ALLOW_UNSIGNED = os.environ.get("MC_UPDATE_ALLOW_UNSIGNED") == "1"


def channel():
    """当前通道：环境变量 > 配置文件 > 默认稳定版"""
    env = (os.environ.get("MC_UPDATE_CHANNEL") or "").strip().lower()
    if env in CHANNELS:
        return env
    try:
        import config as cfgmod
        cfg = cfgmod.load()
        value = str(cfg.get("channel") or "").strip().lower()
        if value in CHANNELS:
            return value
    except Exception:
        pass
    return DEFAULT_CHANNEL


def manifest_url():
    """环境变量可以整个覆盖（调试/自建镜像），否则按通道拼"""
    override = os.environ.get("MC_UPDATE_URL")
    if override:
        return override
    return BASE_URL + CHANNELS.get(channel(), CHANNELS[DEFAULT_CHANNEL])


MANIFEST_URL = manifest_url()
# 必须带一个自己的 User-Agent：Cloudflare 会把默认的 "Python-urllib/3.x" 当爬虫拦掉(403)
BROWSER_UA = "Mozilla/5.0 (compatible; mc-seed-toolkit-updater)"

# 更新时绝不覆盖 / 绝不删除的东西
KEEP = {".mc-tool.json", ".tool-config.json", "记录", "logs", ".build-cache", "runtime",
        "__pycache__", ".git"}

RECORDS = os.path.join(ROOT, "记录")
BACKUP_DIR = os.path.join(RECORDS, ".update-backup")
DIFF_DIR = os.path.join(RECORDS, "更新日志")
MANAGED_FILE = os.path.join(RECORDS, ".managed-files.json")
KEEP_BACKUPS = 3                 # 只留最近几个版本的备份
RETRY_DELAYS = (0.0, 0.3, 0.8, 1.5)   # Windows 上文件被占用时的重试节奏


# ------------------------------------------------------------------ 版本
def local_version():
    try:
        with open(VERSION_FILE, encoding="utf-8") as fh:
            raw = fh.read().strip()
    except OSError:
        return "0.0.0"
    return normalize_version(raw)


def normalize_version(text):
    """'V1.5.0' / 'v1.5.0' / ' 1.5.0 ' 都统一成 '1.5.0'（主版本.小更新.补丁号）"""
    text = str(text or "").strip()
    if text[:1] in ("v", "V"):
        text = text[1:]
    return text or "0.0.0"


def parse_version(text):
    """把版本号拆成能比较的元组：(主, 次, 补丁, 是不是正式版, 预发布序号)

    规则按 semver 的习惯来：**带 -beta 的排在同一个号的正式版前面**
        1.9.1 < 1.10.0-beta.1 < 1.10.0-beta.2 < 1.10.0
    所以测试版用户能一路升到正式版，而正式版用户永远不会被推去 beta
    （那要靠通道隔离，不是靠这个函数）。
    """
    text = normalize_version(text)
    main, _, pre = str(text or "").partition("-")
    nums = []
    for part in main.split("."):
        digits = ""
        for ch in part:
            if ch.isdigit():
                digits += ch
            else:
                break
        nums.append(int(digits) if digits else 0)
    while len(nums) < 3:
        nums.append(0)
    stage, stage_num = 1, 0                # 1 = 正式版
    if pre:
        # beta.2 / rc1 / 随便什么都行：预发布阶段 = 0，后面跟的数字拿来排先后
        stage = 0
        tail = ""
        for ch in pre:
            if ch.isdigit():
                tail += ch
            elif tail:
                break
        stage_num = int(tail) if tail else 0
    return tuple(nums[:3]) + (stage, stage_num)


def is_prerelease(text):
    """这个版本号是不是测试版"""
    return "-" in normalize_version(text)


def is_newer(remote, local):
    return parse_version(remote) > parse_version(local)


# ------------------------------------------------------------------ 网络
def fetch_manifest():
    """拿线上的 manifest；任何问题都抛异常，交给调用方决定怎么办"""
    check_url(MANIFEST_URL)
    man = json.loads(_open(MANIFEST_URL).read().decode("utf-8"))
    return man


def check_url(url):
    """只允许 https + 白名单域名（防 DNS/域名被指到别处，也防有人拿 http 中间人）"""
    from urllib.parse import urlparse
    u = urlparse(url)
    if u.scheme != "https":
        raise ValueError(f"更新地址必须是 https（现在是 {u.scheme or '空'}）")
    if ALLOWED_HOSTS and u.hostname not in ALLOWED_HOSTS:
        raise ValueError(f"更新地址不是我们认可的域名：{u.hostname}")
    return True


def verify_release(man):
    """验签 + 校验清单内容。返回 (是否可信, 说明)"""
    if release is None:
        return False, "客户端里没有签名校验模块（release.py 丢了？）"
    ok, why = release.verify_manifest(man)
    if not ok:
        return False, why
    if str(man.get("name")) != "mc-seed-toolkit":
        return False, f'清单里的名字不对：{man.get("name")!r}'
    if not str(man.get("version") or "").strip():
        return False, "清单里没有版本号"
    for field in ("url", "sha256", "size"):
        if not man.get(field):
            return False, f"清单里缺少 {field}"
    check_url(str(man["url"]))                    # 下载地址也要过白名单
    return True, "签名有效"


def _agent():
    return f"mc-seed-toolkit/{local_version()}"


def _open(url, timeout=None):
    """打开一个 URL；万一被 Cloudflare 按 UA 拦了，换浏览器式 UA 再试一次"""
    headers = {"User-Agent": _agent(), "Cache-Control": "no-cache"}
    try:
        return urllib.request.urlopen(
            urllib.request.Request(url, headers=headers), timeout=timeout or TIMEOUT)
    except urllib.error.HTTPError as e:
        if e.code not in (403, 406):
            raise
        headers["User-Agent"] = BROWSER_UA
        return urllib.request.urlopen(
            urllib.request.Request(url, headers=headers), timeout=timeout or TIMEOUT)


def download(url, dest, expect_sha256=None, expect_size=None, on_progress=None):
    h = hashlib.sha256()
    got = 0
    with _open(url, timeout=TIMEOUT * 10) as resp, open(dest, "wb") as out:
        while True:
            chunk = resp.read(256 * 1024)
            if not chunk:
                break
            out.write(chunk)
            h.update(chunk)
            got += len(chunk)
            if on_progress:
                on_progress(got, expect_size)
    if expect_size and got != expect_size:
        raise RuntimeError(f"大小对不上（收到 {got}，清单说应该是 {expect_size}）"
                           f"—— 可能是下载站的缓存还没过期，过几分钟再试一次")
    if expect_sha256 and h.hexdigest().lower() != str(expect_sha256).lower():
        raise RuntimeError("sha256 校验失败（下载不完整或者线上文件被换过）")
    return got


# ------------------------------------------------------------------ 解压覆盖
def _top_dir(names):
    """zip 里如果所有文件都在同一个顶层目录下（打包就是这样的），返回那个目录名"""
    tops = {n.split("/", 1)[0] for n in names if n.strip("/")}
    if len(tops) == 1:
        only = tops.pop()
        if all(n == only or n.startswith(only + "/") for n in names if n.strip("/")):
            return only
    return None


def apply_zip(zip_path, verbose=True):
    """把 zip 解出来覆盖到工具目录。

    返回 {'changed': 换掉几个, 'skipped': 没变跳过几个, 'failed': [(相对路径, 原因), ...]}

    几个讲究：
      · 内容一样的文件直接跳过（不做无谓的写，少一次被占用的机会）
      · 先写 xxx.new 再 os.replace 原子替换 —— 中途崩了也不会剩半个文件
      · 被占用（Windows 上 WinError 32）就等一会儿重试
      · 换之前把旧的备份到 记录/.update-backup/<版本>/
    """
    tmp = tempfile.mkdtemp(prefix="mc-update-")
    result = {"changed": 0, "skipped": 0, "failed": []}
    try:
        with zipfile.ZipFile(zip_path) as z:
            names = z.namelist()
            z.extractall(tmp)
        top = _top_dir(names)
        src = os.path.join(tmp, top) if top else tmp
        if not os.path.isfile(os.path.join(src, "app", "tool.py")):
            raise RuntimeError("这个包里没有 app/tool.py，不像工具包，先不动")

        backup = os.path.join(BACKUP_DIR, local_version())
        for dirpath, dirnames, filenames in os.walk(src):
            rel_dir = os.path.relpath(dirpath, src)
            rel_dir = "" if rel_dir == "." else rel_dir
            parts = rel_dir.split(os.sep) if rel_dir else []
            if parts and parts[0] in KEEP:
                dirnames[:] = []
                continue
            os.makedirs(os.path.join(ROOT, rel_dir), exist_ok=True)
            for name in filenames:
                if rel_dir == "" and name in KEEP:
                    continue
                src_file = os.path.join(dirpath, name)
                dst_file = os.path.join(ROOT, rel_dir, name)
                rel = os.path.join(rel_dir, name) if rel_dir else name
                if _same_file(src_file, dst_file):
                    result["skipped"] += 1
                    continue
                _backup_file(dst_file, backup, rel)
                ok, why = _replace_file(src_file, dst_file)
                if ok:
                    result["changed"] += 1
                else:
                    result["failed"].append((rel, why))
        _purge_pycache()
        if verbose:
            print(f"（替换 {result['changed']} 个文件，跳过 {result['skipped']} 个没变的）")
        return result
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- 覆盖细节
def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _same_file(a, b):
    """大小 + 内容都一样？一样就别写了（少一次被占用的机会）"""
    try:
        if os.path.getsize(a) != os.path.getsize(b):
            return False
        return _sha256_file(a) == _sha256_file(b)
    except OSError:
        return False


def _replace_file(src, dst):
    """原子替换 + 被占用就重试。返回 (成功?, 失败原因)"""
    tmp_new = dst + ".new"
    last = None
    for delay in RETRY_DELAYS:
        if delay:
            time.sleep(delay)
        try:
            shutil.copy2(src, tmp_new)
            os.replace(tmp_new, dst)          # 同目录内，原子替换
            return True, None
        except OSError as e:
            last = e
            try:
                if os.path.exists(tmp_new):
                    os.remove(tmp_new)
            except OSError:
                pass
    return False, _explain(last)


def _explain(err):
    """把 OSError 翻译成人话（Windows 的占用错误码单独说）"""
    code = getattr(err, "winerror", None)
    if code in (5, 32) or (code is None and isinstance(err, PermissionError)):
        return "文件被占用（可能有程序正开着它，或有杀毒软件在扫）"
    if isinstance(err, PermissionError):
        return "没有写权限（目录只读？U 盘写保护？）"
    if isinstance(err, FileNotFoundError):
        return "路径不见了"
    return f"{type(err).__name__}: {err}"


def _backup_file(path, backup_root, rel):
    """把要覆盖掉的旧文件存一份（更新失败时可以手动倒回去）"""
    if not os.path.isfile(path):
        return
    dst = os.path.join(backup_root, rel)
    try:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(path, dst)
    except OSError:
        pass


def _purge_pycache():
    """更新完把 __pycache__ 清掉：免得旧的 .pyc 跟新代码对不上"""
    for root, dirs, _files in os.walk(ROOT):
        if any(part in (".git", "runtime", "记录") for part in root.split(os.sep)):
            dirs[:] = []
            continue
        for d in list(dirs):
            if d == "__pycache__":
                shutil.rmtree(os.path.join(root, d), ignore_errors=True)
                dirs.remove(d)


def _prune_backups():
    """备份只留最近几个版本"""
    try:
        names = sorted((d for d in os.listdir(BACKUP_DIR)
                        if os.path.isdir(os.path.join(BACKUP_DIR, d))),
                       key=lambda d: os.path.getmtime(os.path.join(BACKUP_DIR, d)))
        for old in names[:-KEEP_BACKUPS]:
            shutil.rmtree(os.path.join(BACKUP_DIR, old), ignore_errors=True)
    except OSError:
        pass


def _preflight():
    """先试试这个目录到底能不能写 —— 免得改到一半才发现是只读盘"""
    probe = os.path.join(ROOT, ".update-write-test")
    try:
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("ok")
        os.remove(probe)
        return True, None
    except OSError as e:
        return False, _explain(e)


# ---------------------------------------------------------------- 差异对比
def _short_hash(path):
    try:
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()[:16]
    except OSError:
        return None


def _load_managed():
    try:
        with open(MANAGED_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
        return data.get("files", {}) if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_managed(files, version):
    try:
        os.makedirs(os.path.dirname(MANAGED_FILE), exist_ok=True)
        with open(MANAGED_FILE, "w", encoding="utf-8") as fh:
            json.dump({"version": version, "files": files}, fh,
                      ensure_ascii=False, indent=2, sort_keys=True)
    except OSError:
        pass


def plan(man):
    """下载之前就能算出来的差异：哪些要改、哪些是新增、哪些该废弃。

    靠的是清单里的 files（每个文件的短哈希），不用先下 1MB 的包。
    """
    files = man.get("files") or {}
    if not files:
        return None                      # 老版本清单没这个字段，退回"老老实实全覆盖"
    added, changed, same = [], [], 0
    for rel, digest in sorted(files.items()):
        local = os.path.join(ROOT, rel)
        if not os.path.isfile(local):
            added.append(rel)
        elif _short_hash(local) == digest:
            same += 1
        else:
            changed.append(rel)
    # 废弃：上次是我们发的，这次包里没有了，而且你没改过它
    old = _load_managed()
    gone = []
    for rel, digest in sorted(old.items()):
        if rel in files:
            continue
        local = os.path.join(ROOT, rel)
        if os.path.isfile(local) and _short_hash(local) == digest:
            gone.append(rel)
    return {"added": added, "changed": changed, "same": same, "gone": gone}


def describe(p, limit=8):
    """把差异写成人看的一行行"""
    if p is None:
        return ["（这份清单没带文件列表，只能整个覆盖一遍）"]
    out = [f"这次更新：改 {len(p['changed'])} 个、新增 {len(p['added'])} 个、"
           f"废弃 {len(p['gone'])} 个，其余 {p['same']} 个文件没动"]
    for tag, items in (("改", p["changed"]), ("新", p["added"]), ("删", p["gone"])):
        for rel in items[:limit]:
            out.append(f"  {tag}  {rel}")
        if len(items) > limit:
            out.append(f"  {tag}  …还有 {len(items) - limit} 个")
    return out


def file_diffs(zip_path, only_text_limit=400):
    """把"本地旧文件 vs 包里新文件"逐行比一遍。

    返回 (逐文件统计, 完整 diff 文本)。二进制文件只报"变了"，不比内容。
    """
    import difflib
    stats, full = [], []
    tmp = tempfile.mkdtemp(prefix="mc-diff-")
    try:
        with zipfile.ZipFile(zip_path) as z:
            names = z.namelist()
            z.extractall(tmp)
        top = _top_dir(names)
        src = os.path.join(tmp, top) if top else tmp
        for dirpath, dirnames, filenames in os.walk(src):
            rel_dir = os.path.relpath(dirpath, src)
            rel_dir = "" if rel_dir == "." else rel_dir
            if rel_dir.split(os.sep)[0] in KEEP:
                dirnames[:] = []
                continue
            for name in sorted(filenames):
                rel = os.path.join(rel_dir, name) if rel_dir else name
                new_path = os.path.join(dirpath, name)
                old_path = os.path.join(ROOT, rel)
                if _same_file(new_path, old_path):
                    continue
                old_lines, new_lines, binary = [], [], False
                try:
                    with open(old_path, encoding="utf-8") as fh:
                        old_lines = fh.read().splitlines()
                    with open(new_path, encoding="utf-8") as fh:
                        new_lines = fh.read().splitlines()
                except (OSError, UnicodeDecodeError):
                    binary = True                # 新文件，或者二进制（jar/exe）
                if binary:
                    stats.append((rel, None, None, "二进制" if os.path.exists(old_path) else "新增"))
                    full.append(f"=== {rel} ===\n（二进制或新文件，不比内容）\n")
                    continue
                diff = list(difflib.unified_diff(
                    old_lines, new_lines, fromfile=f"a/{rel}", tofile=f"b/{rel}", lineterm=""))
                plus = sum(1 for l in diff if l.startswith("+") and not l.startswith("+++"))
                minus = sum(1 for l in diff if l.startswith("-") and not l.startswith("---"))
                if not diff:
                    continue
                stats.append((rel, plus, minus, "改"))
                full.append("=== " + rel + " ===\n" + "\n".join(diff[:only_text_limit]) + "\n")
        return stats, "\n".join(full)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def save_diff(text, old_ver, new_ver):
    """把完整 diff 存进 记录/更新日志/，想看细节随时翻"""
    try:
        os.makedirs(DIFF_DIR, exist_ok=True)
        path = os.path.join(DIFF_DIR, f"{old_ver}→{new_ver}.diff")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path
    except OSError:
        return None


def remove_obsolete(gone, version):
    """把废弃文件挪进备份目录（不是直接删，随时能翻回来）"""
    moved = 0
    dest_root = os.path.join(BACKUP_DIR, version, "废弃")
    for rel in gone:
        src = os.path.join(ROOT, rel)
        dst = os.path.join(dest_root, rel)
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.move(src, dst)
            moved += 1
        except OSError:
            pass
    return moved


def _report_diffs(zip_path, old_ver, new_ver):
    """下载完、替换前：逐文件报一下改了多少行，并把完整 diff 存下来"""
    try:
        stats, full = file_diffs(zip_path)
    except Exception as e:
        print(f"  （算差异的时候出错了：{e}）")
        return
    if not stats:
        return

    # 先把"看得懂的"排在前面：app/ 下的代码 > 其它文本 > 二进制
    def rank(item):
        rel, plus, _minus, kind = item
        if plus is not None:
            return (0 if rel.replace("\\", "/").startswith("app/") else 1, rel)
        return (2, rel)

    text = sorted([s for s in stats if s[1] is not None], key=rank)
    binary = sorted([s for s in stats if s[1] is None], key=rank)
    both = text + binary
    print(f"  代码差异（{len(both)} 个文件）：")
    shown = 0
    for rel, plus, minus, kind in both:
        if plus is None or shown >= 15:
            break
        print(f"    {rel}   +{plus} -{minus}")
        shown += 1
    if len(text) > shown:
        print(f"    …还有 {len(text) - shown} 个代码文件")
    if binary:
        kinds = {}
        for _rel, _p, _m, kind in binary:
            kinds[kind] = kinds.get(kind, 0) + 1
        detail = "、".join(f"{k} {v} 个" for k, v in kinds.items())
        names = "、".join(os.path.basename(r) for r, *_ in binary[:3])
        print(f"    （另有 {detail}：{names}{'…' if len(binary) > 3 else ''}）")
    path = save_diff(full, old_ver, new_ver)
    if path:
        print(f"    完整 diff：记录/更新日志/{os.path.basename(path)}")


# ---------------------------------------------------------------- 回滚
def backups():
    """能回滚到哪些版本：[(版本, 时间戳, 文件数)]，新的在前"""
    out = []
    try:
        for name in os.listdir(BACKUP_DIR):
            path = os.path.join(BACKUP_DIR, name)
            if not os.path.isdir(path) or name.startswith("."):
                continue
            count = 0
            for _root, _dirs, files in os.walk(path):
                if os.path.basename(_root) == "废弃":
                    continue
                count += len(files)
            out.append((name, os.path.getmtime(path), count))
    except OSError:
        return []
    return sorted(out, key=lambda t: -t[1])


def rollback(version, verbose=True):
    """把 <version> 那一次的备份倒回去（连当时被删掉的废弃文件也放回来）。

    只动备份里有的文件，别的一概不碰 —— 种子、记录、自带 Java 都在 KEEP 名单里。
    返回 (成功?, 说明)。
    """
    src = os.path.join(BACKUP_DIR, version)
    if not os.path.isdir(src):
        return False, f"没有 {version} 的备份"
    restored, failed = 0, []

    def put(rel, from_path):
        nonlocal restored
        dst = os.path.join(ROOT, rel)
        os.makedirs(os.path.dirname(dst) or ROOT, exist_ok=True)
        ok, why = _replace_file(from_path, dst)
        if ok:
            restored += 1
        else:
            failed.append((rel, why))

    for root, dirs, files in os.walk(src):
        rel_dir = os.path.relpath(root, src)
        rel_dir = "" if rel_dir == "." else rel_dir
        if rel_dir == "废弃":
            dirs[:] = []
            continue
        for name in files:
            if rel_dir == "" and name in KEEP:
                continue
            rel = os.path.join(rel_dir, name) if rel_dir else name
            put(rel, os.path.join(root, name))

    gone_dir = os.path.join(src, "废弃")
    for root, _dirs, files in os.walk(gone_dir):
        rel_dir = os.path.relpath(root, gone_dir)
        rel_dir = "" if rel_dir == "." else rel_dir
        for name in files:
            rel = os.path.join(rel_dir, name) if rel_dir else name
            put(rel, os.path.join(root, name))

    if verbose:
        print(f"  （放回 {restored} 个文件）")
    if failed:
        head = "；".join(f"{r}：{w}" for r, w in failed[:3])
        return False, f"有 {len(failed)} 个文件没放回去：{head}"
    return True, f"已回滚到 {version}（重启一下工具就是那个版本）"


# ------------------------------------------------------------------ 对外接口
def check():
    """问一下线上有没有新版本。返回 (manifest, 提示语)；网络不通返回 (None, 原因)"""
    local = local_version()
    try:
        check_url(MANIFEST_URL)
        man = fetch_manifest()
    except urllib.error.HTTPError as e:
        if e.code == 404 and channel() != DEFAULT_CHANNEL:
            return None, f"这个通道还没有发布过（{CHANNEL_NAMES[channel()]}）"
        return None, f"连不上下载站（HTTP {e.code}）"
    except (urllib.error.URLError, OSError, ValueError) as e:
        return None, f"连不上下载站（{e}）"
    trust, why = verify_release(man)
    if not trust and not ALLOW_UNSIGNED:
        return None, (f"⚠⚠ 清单签名校验没过：{why}\n"
                      f"     这次不更新。如果不是你自己在调试，说明下载站可能被人动了手脚，"
                      f"先别用更新，去群里问一下。")
    if not trust:
        print("  ⚠ 正在用 MC_UPDATE_ALLOW_UNSIGNED=1 跳过签名校验（只有调试该这么干）")
    remote = str(man.get("version") or "").strip()
    if not remote:
        return None, "线上的 manifest 里没有版本号"
    if not is_newer(remote, local):
        return None, f"已经是最新的（本地 {local}，线上 {remote}）"
    return man, f"有新版本：本地 {local} -> 线上 {remote}"


def update(force=False, verbose=True):
    """检查 + 更新。返回 (是否更新了, 说明文字)"""
    local = local_version()
    try:
        man = fetch_manifest()
    except urllib.error.HTTPError as e:
        if e.code == 404 and channel() != DEFAULT_CHANNEL:
            return False, ""              # 测试版通道还没发过东西：安静点，别每次启动都念
        return False, f"连不上下载站，跳过更新（HTTP {e.code}）"
    except (urllib.error.URLError, OSError, ValueError) as e:
        return False, f"连不上下载站，跳过更新（{e}）"

    remote = str(man.get("version") or "").strip()
    if not remote:
        return False, "线上的 manifest 里没有版本号，跳过"
    if not force and not is_newer(remote, local):
        return False, ""                      # 静默：平时就该这么安静

    # 签名没过的包，一律不下载、不解压、不替换
    trust, why = verify_release(man)
    if not trust and not ALLOW_UNSIGNED:
        return False, (f"⚠⚠ 清单签名校验没过：{why} —— 已拒绝更新。\n"
                       f"     可能是下载站被篡改了，先别更新，去群里问一下。")
    if not trust:
        print("  ⚠ 正在用 MC_UPDATE_ALLOW_UNSIGNED=1 跳过签名校验（只有调试该这么干）")
    try:
        check_url(str(man.get("url") or ""))
    except ValueError as e:
        return False, f"下载地址不安全：{e}"

    url = man.get("url") or (BASE_URL + "/" + str(man.get("zip") or ""))
    if not url or url.endswith("/"):
        return False, "manifest 里没写下载地址，跳过"

    if verbose:
        size = man.get("size")
        size_text = f"，{size / 1024 / 1024:.1f} MB" if size else ""
        print(f"发现新版本 {local} → {remote}{size_text}，正在自动更新…")
        # 下载前先把差异说清楚（靠清单里的文件哈希，不用先下包）
        plan_now = plan(man)
        for line in describe(plan_now):
            print("  " + line)

    can_write, why = _preflight()
    if not can_write:
        return False, f"这个目录现在写不进去（{why}），跳过更新"

    tmp_zip = os.path.join(tempfile.gettempdir(), f"mc-update-{remote}.zip")
    try:
        download(url, tmp_zip, man.get("sha256"), man.get("size"))
        if verbose:
            _report_diffs(tmp_zip, local, remote)
        result = apply_zip(tmp_zip, verbose=verbose)
    except Exception as e:
        return False, f"更新失败：{e}（这次就先按旧版本跑）"
    finally:
        try:
            os.remove(tmp_zip)
        except OSError:
            pass

    _prune_backups()

    # 把废弃文件挪到备份里（只挪"上次是我们发的、你也没改过"的）
    gone = (plan(man) or {}).get("gone") or []
    if gone:
        moved = remove_obsolete(gone, remote)
        if moved and verbose:
            print(f"  （清掉 {moved} 个废弃文件，旧的放在 记录/.update-backup/{remote}/废弃/）")
    if man.get("files"):
        _save_managed(man["files"], remote)

    # 分个级：app/ 里的代码没换上 = 更新其实没成；其它（out/、文档、脚本）可以先放着
    failed = result["failed"]
    critical = [(rel, why) for rel, why in failed if _is_critical(rel)]
    minor = [(rel, why) for rel, why in failed if not _is_critical(rel)]

    if critical:
        lines = "；".join(f"{rel}：{why}" for rel, why in critical[:3])
        more = f"（还有 {len(critical) - 3} 个）" if len(critical) > 3 else ""
        return False, (f"有 {len(critical)} 个关键文件没换成 —— {lines}{more}。"
                       f"先按旧版本跑，下次启动会自动重试")

    if minor:
        print(ui_warn_minor(minor))

    try:                                       # 记下新版本号（关键文件都换上了才记）
        with open(VERSION_FILE, "w", encoding="utf-8") as fh:
            fh.write(remote + "\n")
    except OSError:
        pass
    return True, f"已更新到 {remote}（重启一下工具就是新版）"


def _is_critical(rel):
    """app/ 下的程序代码是关键的；out/、文档、启动脚本被占用可以先放着"""
    return rel.replace("\\", "/").startswith("app/")


def ui_warn_minor(minor):
    """非关键文件没换上的提醒（比如 out/findstruct.exe 还在被占用）"""
    head = "；".join(f"{rel}：{why}" for rel, why in minor[:3])
    more = f"（还有 {len(minor) - 3} 个）" if len(minor) > 3 else ""
    return f"  ⚠ {len(minor)} 个非关键文件没换成：{head}{more} —— 不影响用，下次启动会再试"


def maybe_update():
    """启动时悄悄检查一遍；有更新就自动拉下来。任何错误都不打扰用户。"""
    if os.environ.get("MC_NO_UPDATE") == "1":
        return
    try:
        changed, msg = update(verbose=True)
    except Exception:
        return
    if not msg:
        return                      # 没有新版本：平时就该这么安静
    if changed:
        print("* " + msg)
    else:
        # 失败要说出来 —— 尤其是"签名不对"，那是"下载站可能被人动了手脚"的信号，
        # 绝不能悄悄咽掉
        print()
        print(msg)
        print()


def auto_update_enabled():
    """不问、直接更新的情况：
       · MC_NO_UPDATE_ASK=1（老行为，想安静）
       · 不是真终端（脚本/管道里调用，问了也没人答）
    """
    if os.environ.get("MC_NO_UPDATE_ASK") == "1" or os.environ.get("MC_UPDATE_NO_ASK") == "1":
        return True
    try:
        import ui
        return not ui.INTERACTIVE
    except Exception:
        return False


def restart_into_new_version():
    """更新完直接重启成新版（省得用户自己关掉再开）。
    只有一个来回：重启后会带 MC_JUST_RESTARTED=1，避免万一循环。"""
    if not sys.stdin.isatty() or os.environ.get("MC_JUST_RESTARTED") == "1":
        return False
    os.environ["MC_JUST_RESTARTED"] = "1"
    try:
        print("  正在用新版重启…")
        sys.stdout.flush()
        os.execv(sys.executable, [sys.executable] + sys.argv)
    except Exception as e:
        print(f"  （自动重启没成：{e}，手动关掉再开一次就行）")
        return False


def main():
    force = "--force" in sys.argv
    local = local_version()
    if force:
        changed, msg = update(force=True)
        print(msg or "没有更新")
        return
    man, msg = check()
    print(f"本地版本：{local}")
    print(msg)
    if man:
        print(f"下载地址：{man.get('url') or man.get('zip')}")
        if man.get("notes"):
            print(f"更新说明：{man['notes']}")
        if input("现在就更新吗？ [Y/n]: ").strip().lower() != "n":
            changed, m = update(verbose=True)
            print(m or "没有更新")


if __name__ == "__main__":
    main()
