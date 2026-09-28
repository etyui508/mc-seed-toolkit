#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真 pty 驱动：像用户那样"看见提示再敲答案"。

为什么非得这样：
  · 工具会看 stdout 是不是真终端来决定画不画框线、颜色、进度动画。
    用管道喂 stdin，屏幕跟用户看到的不是一回事，拿它数"漏了多少中文"不可信。
  · 管道是把按键一次性全塞进去的：只要有一屏问的问题跟脚本对不上，
    后面就全错位 —— 测试会**静悄悄只跑了一半**还报"通过"。

用法：

    from ttydrive import drive, strip_ansi

    out, rc = drive(["bash", "run.sh"], [(r"Choose:", "2")], cwd=box)
    out, rc = drive(["bash", "run.sh"], look_at_screen)     # 回调版

回调版签名：answer(segment, index, state) -> str
    segment 是"上一个提示符到这一个提示符之间"的输出（也就是这一屏的内容），
    返回要敲的那一行（不要带换行）。
"""
import fcntl
import os
import pty
import re
import select
import struct
import subprocess
import termios
import time

_ANSI = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[()][A-Z0-9]")


def strip_ansi(text):
    return _ANSI.sub("", str(text))


def _prompt_positions(text):
    """所有"提示符"出现的位置（按顺序）：优先认 ❯，退化认 "> "。"""
    pos = [m.start() for m in re.finditer(re.escape("❯ "), text)]
    if pos:
        return pos
    return [m.start() for m in re.finditer(r"> ", text)]


def _normalize(data):
    return data.replace("\r\n", "\n").replace("\r", "\n")


def drive(argv, answer, cwd=None, env=None, timeout=900, cols=100, rows=40,
          settle=0.30):
    """跑一个交互式程序，按提示应答，返回 (屏幕文本（已去 ANSI）, 退出码)。

    answer：回调 answer(segment, index, state) -> str，或者 [(正则, 回答), ...]。
    settle：提示符出现后，再等这么久没有新输出才算"这一屏画完了"，避免抢答。
    """
    if not callable(answer):
        steps = list(answer)

        def answer(segment, index, state, _steps=steps):
            for pat, reply in _steps:
                if re.search(pat, segment):
                    return reply
            return ""

    state = {}
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    def _child_setup():
        os.setsid()
        fcntl.ioctl(0, termios.TIOCSCTTY, 0)

    run_env = dict(os.environ)
    run_env.setdefault("TERM", "xterm-256color")
    if env:
        run_env.update({k: str(v) for k, v in env.items()})

    proc = subprocess.Popen(argv, stdin=slave, stdout=slave, stderr=slave,
                            cwd=cwd, env=run_env, preexec_fn=_child_setup,
                            close_fds=True)
    os.close(slave)

    chunks = []
    text = ""
    handled = 0
    started = time.monotonic()
    last_output = time.monotonic()
    killed = False

    try:
        while True:
            if time.monotonic() - started > timeout:
                killed = True
                break
            try:
                ready, _, _ = select.select([master], [], [], 0.1)
            except (OSError, ValueError):
                break
            if ready:
                try:
                    chunk = os.read(master, 65536)
                except OSError:                 # 子进程没了，pty 会报 EIO
                    break
                if not chunk:
                    break
                chunks.append(chunk)
                text = strip_ansi(_normalize(b"".join(chunks).decode("utf-8", "replace")))
                last_output = time.monotonic()
                continue

            # 没有新输出：看看是不是停在提示符上，是就应答
            positions = _prompt_positions(text)
            if len(positions) > handled and time.monotonic() - last_output >= settle:
                pos = positions[handled]
                prev = positions[handled - 1] + 1 if handled else 0
                segment = text[prev:pos]
                reply = answer(segment, handled, state)
                if reply is None:
                    reply = ""
                try:
                    os.write(master, reply.encode("utf-8") + b"\n")
                except OSError:
                    break
                handled += 1
                last_output = time.monotonic()
                continue
            if proc.poll() is not None:
                # 进程退了，但可能还有尾巴没读完，再抓一轮
                try:
                    ready, _, _ = select.select([master], [], [], 0.2)
                except (OSError, ValueError):
                    break
                if not ready:
                    break
    finally:
        if proc.poll() is None:
            if killed:
                proc.kill()
            else:
                proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        try:
            os.close(master)
        except OSError:
            pass

    rc = proc.returncode if proc.returncode is not None else (124 if killed else 0)
    if killed:
        text += f"\n[ttydrive] 超过 {timeout}s 还没结束，已杀掉\n"
    return text, rc


def looks_done(text, words=("Bye", "再见")):
    """程序是不是自己正常退出了（走到"再见"那一步）"""
    tail = text[-400:]
    return any(w in tail for w in words)


if __name__ == "__main__":                  # 手工试一把：python3 ttydrive.py bash run.sh
    import sys
    argv = sys.argv[1:] or ["bash", "run.sh"]
    out, code = drive(argv, [(r"Choose:", "0")], timeout=120)
    print(out)
    print(f"\nrc={code}  提示符应答了 {out.count('❯ ')} 次")
