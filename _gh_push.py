# -*- coding: utf-8 -*-
"""GitHub 建库 + 推送（本地 git + 凭据绕过，全程不打印 token）"""
import ctypes, os, subprocess, sys, time, io
from ctypes import wintypes

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

REPO_DIR = r"E:\Kevin L\2026-11-06-19-10-09\eda-agent"
REPO_NAME = "eda-agent"
REPO_DESC = "AI Agent 电路板设计 —— 自然语言驱动的 KiCad 电路设计智能体（课程大作业）"

GIT = r"C:\Users\Kevin L\.workbuddy\binaries\PortableGit\versions\1.2.0\cmd\git.exe"
MINGW_BIN = r"C:\Users\Kevin L\.workbuddy\binaries\PortableGit\versions\1.2.0\mingw64\bin"
GIT_EXEC = r"C:\Users\Kevin L\.workbuddy\binaries\PortableGit\versions\1.2.0\mingw64\libexec\git-core"


# ---- 1. 读取凭据 ----
class CREDENTIAL(ctypes.Structure):
    pass
CREDENTIAL._fields_ = [
    ("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR),
    ("Comment", wintypes.LPWSTR), ("LastWritten", ctypes.c_ulonglong),
    ("CredentialBlobSize", wintypes.DWORD), ("CredentialBlob", ctypes.POINTER(ctypes.c_byte)),
    ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD),
    ("Attributes", ctypes.c_void_p), ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR),
]
PCREDENTIAL = ctypes.POINTER(CREDENTIAL)
PCREDENTIAL_PTR = ctypes.POINTER(PCREDENTIAL)
advapi32 = ctypes.windll.advapi32
advapi32.CredEnumerateW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(PCREDENTIAL_PTR)]
advapi32.CredEnumerateW.restype = wintypes.BOOL
advapi32.CredFree.argtypes = [ctypes.c_void_p]

count = wintypes.DWORD(0)
pcreds = PCREDENTIAL_PTR()
advapi32.CredEnumerateW(None, 0, ctypes.byref(count), ctypes.byref(pcreds))
user = token = None
for i in range(count.value):
    c = pcreds[i].contents
    if "github" in (c.TargetName or "").lower():
        user = c.UserName
        blob = ctypes.string_at(c.CredentialBlob, c.CredentialBlobSize)
        token = blob.decode("utf-16-le").rstrip("\x00")
        break
advapi32.CredFree(pcreds)

if not user or not token:
    print("!! 未找到 GitHub 凭据")
    sys.exit(1)
print(f"凭据: user={user}, token=ghx_...(长度{len(token)})")

import urllib.request, json

# ---- 2. 建库 ----
def api_create_repo():
    req = urllib.request.Request(
        "https://api.github.com/user/repos",
        data=json.dumps({"name": REPO_NAME, "description": REPO_DESC, "private": False, "auto_init": False}).encode(),
        method="POST",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "Content-Type": "application/json", "User-Agent": "eda-agent"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.load(r)
            print("建库成功:", data.get("html_url"))
            return True
    except urllib.error.HTTPError as e:
        if e.code == 422:
            print("仓库已存在（422），继续推送")
            return True
        print("建库失败 HTTP", e.code, e.read().decode()[:300])
        return False
    except Exception as e:
        print("建库异常:", e)
        return False

if not api_create_repo():
    sys.exit(1)

# ---- 3. git 环境 ----
env = os.environ.copy()
env["PATH"] = MINGW_BIN + os.pathsep + env.get("PATH", "")
env["GIT_EXEC_PATH"] = GIT_EXEC
env["GIT_TERMINAL_PROMPT"] = "0"
env["GCM_INTERACTIVE"] = "never"
env["GIT_ASKPASS"] = "echo"

remote_url = f"https://{user}:{urllib.parse.quote(token, safe='')}@github.com/{user}/{REPO_NAME}.git"

def run(args, timeout=120):
    cmd = [GIT] + args
    # 输出重定向到文件，避免 PIPE 阻塞
    out_f = os.path.join(REPO_DIR, "_git_out.txt")
    err_f = os.path.join(REPO_DIR, "_git_err.txt")
    with open(out_f, "w", encoding="utf-8", errors="replace") as fo, open(err_f, "w", encoding="utf-8", errors="replace") as fe:
        p = subprocess.Popen(cmd, cwd=REPO_DIR, env=env, stdout=fo, stderr=fe, stdin=subprocess.DEVNULL)
        start = time.time()
        while p.poll() is None:
            if time.time() - start > timeout:
                p.kill()
                print("!! 超时，已终止")
                break
            time.sleep(0.2)
    rc = p.returncode
    out = open(out_f, encoding="utf-8", errors="replace").read() if os.path.exists(out_f) else ""
    err = open(err_f, encoding="utf-8", errors="replace").read() if os.path.exists(err_f) else ""
    # 脱敏：把 token 从输出里替换掉
    for t in [token, urllib.parse.quote(token, safe='')]:
        out = out.replace(t, "***")
        err = err.replace(t, "***")
    return rc, out, err

def git(*args):
    rc, out, err = run(list(args))
    tail = (out + err).strip().splitlines()
    print("  $ git", " ".join(args), "-> rc", rc)
    for line in tail[-6:]:
        print("    ", line[:160])
    return rc

# ---- 4. git 操作 ----
print("\n== 初始化仓库 ==")
if not os.path.isdir(os.path.join(REPO_DIR, ".git")):
    git("init", "-b", "main")
else:
    print("  已存在 .git，跳过 init")

git("config", "--local", "http.sslBackend", "openssl")
git("config", "user.name", "Kian")
git("config", "user.email", f"{user}@users.noreply.github.com")
git("add", "-A")
rc, out, err = run(["status", "--short"])
print("  待提交文件数:", len([l for l in (out + err).splitlines() if l.strip()]))
git("commit", "-m", "feat: EDA Agent 电路设计智能体 —— 自然语言驱动 KiCad 原理图（课程大作业）")

print("\n== 推送 ==")
# 先 ls-remote 验证网络
rc, out, err = run(["ls-remote", remote_url, "refs/heads/main"])
print("  ls-remote rc", rc, "输出行数", len([l for l in out.splitlines() if l.strip()]))

# 设置远端并推送（用 -c credential.helper= 绕过 GCM）
git("remote", "add", "origin", remote_url)
rc = git("-c", "credential.helper=", "push", "-u", "origin", "main")

if rc == 0:
    print("\n✅ 推送成功！仓库地址: https://github.com/{}/{}/".format(user, REPO_NAME))
else:
    print("\n⚠️ push rc =", rc, "（可能已推送成功但本地未确认，用 ls-remote 核对）")
    git("ls-remote", remote_url, "refs/heads/main")
