"""干跑测试：在临时目录跑混淆管线并验证产物（不触碰真实源码，不编译 .pyd）。"""
import importlib
import os
import pkgutil
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "xpai-camera-control" / "scripts"
TMP = Path(tempfile.mkdtemp(prefix="xpai_dryrun_"))

shutil.copytree(SRC, TMP / "scripts",
                ignore=shutil.ignore_patterns("__pycache__", "*.pyd"))
print("tmp:", TMP)

sys.path.insert(0, str(ROOT / "xpai-build"))
import build_toolkit as bt

# 快速参数（干跑不校准）：n=2^10，打包/解码均为毫秒级
bt._N = 2 ** 10
bt._N_LOG2 = 10
bt.ROOT = TMP
bt.TOOLKIT_DIR = TMP / "scripts" / "toolkit"

os.environ["XPAI_VERIFY"] = "1"

# ── 1) 内联解码表达式单元往返 ──
plain = b"/xiaopaitech/device_service"
blob = bt._blob_pack(plain)
ctx = {"cache": "__test_cache", "os_a": "os", "h_a": "hashlib",
       "r_a": "random", "sys": "sys", "blobs": {}}
expr = bt._decode_expr("BLOB", ctx)
compile(expr, "<expr>", "eval")
import hashlib as h_mod
import os as os_mod
import random as rnd_mod
ns = {"BLOB": blob, "__test_cache": {}, "os": os_mod,
      "hashlib": h_mod, "random": rnd_mod}
assert eval(expr, ns) == plain
assert eval(expr, ns) == plain and ns["__test_cache"]   # 二次命中缓存
print("[1] expr roundtrip + cache ok")

# ── 2) 全管线混淆 + 诱饵（含盐池预热并行派生路径） ──
bt.prewarm_derivation(8)
sources = sorted(bt.TOOLKIT_DIR.glob("*.py"))
imported = bt._collect_imported_names(sources)
for src in sources:
    n = bt.obfuscate_file(src, imported)
    text = bt.inject_decoys(src.read_text(encoding="utf-8"))
    compile(text, str(src), "exec")
    src.write_text(text, encoding="utf-8")
    print("[2] obfuscated %s (sensitives=%d)" % (src.name, n))
print("[2] pad decoys:", bt.pad_decoys(sources))

# KEY 字节不得残留，且 auth key 使用处应已内联
ill = (bt.TOOLKIT_DIR / "illumination.py").read_text(encoding="utf-8")
assert "0x72" not in ill and "h.update((" in ill, "auth key 补丁异常"
print("[2] auth-key patch ok")

# ── 3) 运行时验证（快速模式） ──
sys.path.insert(0, str(TMP))
from scripts.toolkit.events import _normalize_private_topic
assert _normalize_private_topic("MD") == "motion"
assert _normalize_private_topic("HD") == "human"
assert _normalize_private_topic("XX") == "xx"
print("[3] _normalize_private_topic ok")

import scripts.toolkit as tk
print("[3] package import ok, __all__:", len(tk.__all__))

# ── 4) 攻击面扫描（模拟 agent：找明文/找解码函数） ──
bad = []
blobs_total = 0
for mi in pkgutil.iter_modules(tk.__path__):
    m = importlib.import_module("scripts.toolkit." + mi.name)
    for k, v in vars(m).items():
        if k == "__doc__":
            continue  # docstring 由 Cython 编译期剥离，.py 直跑时仍可见，不算泄漏
        if isinstance(v, str) and re.search("sk_setting|xiaopaitech|skyworth", v, re.I):
            bad.append("str-leak:" + mi.name + "." + k)
        if callable(v) and re.search(r"(?i)dec|decode|decrypt|xor|secret", k):
            bad.append("decoder:" + mi.name + "." + k)
        if isinstance(v, bytes) and len(v) >= 24:
            blobs_total += 1
assert not bad, bad
assert blobs_total > 0
print("[4] attack-surface ok, module-level blobs:", blobs_total)

# ── 5) VERIFY_CODE 自身语法与关键断言可编译 ──
compile(bt.VERIFY_CODE, "<verify>", "exec")
print("[5] VERIFY_CODE syntax ok")
print("DRYRUN ALL OK")
