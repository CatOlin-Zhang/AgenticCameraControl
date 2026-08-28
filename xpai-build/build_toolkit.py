# -*- coding: utf-8 -*-
"""
build_toolkit.py — 一键构建（请勿将本文件拷入分发目录）

流程：
  1. 校准 scrypt 时间成本参数（使单次解码 ≈ DECODE_TARGET_SECONDS）。
  2. 对 scripts/toolkit/*.py 做敏感常量混淆（强化方案，去预言机）：
     - 每个秘密独立打包为「单一 bytes 包」（salt|参数|乱序密文），无结构指纹
     - 解码以自包含内联表达式形式生成在使用点，模块属性中不留任何解码函数
     - 解码前经 scrypt 派生密钥：单次解码耗时 ≈ 校准值，全量枚举 ≥60 分钟
     - 敏感常量名构建期 AST 重命名为无意义标识符（跨模块导入的名字除外）
     - 注入结构相同的诱饵包，真假不可区分
     - 每次打包都强制往返自检；混淆后强制残留扫描（fail-closed）
  3. Cython 编译为 .pyd（剥离全部 docstring 与函数签名）
  4. 纯 .pyd 状态验证：导入、模拟攻击（找解码入口/指纹/耗时）、关键逻辑
  5. 清理中间产物

用法：由同目录 build.bat 调用（bat 会把工作目录切到项目根）。
本文件通过"特征模式"在源码中发现敏感字面量，自身不保存任何协议明文。

运行时环境变量：
  XPAI_VERIFY=1   快速模式（验证用，scrypt 降到毫秒级）
  XPAI_DECODE_N   覆盖 scrypt 的 n=2^X（调试用，正常勿设）
"""
import hashlib
import math
import os
import random
import re
import shutil
import subprocess
import sys
import sysconfig
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path.cwd()                      # build.bat 保证 cwd = 项目根目录
TOOLKIT_DIR = ROOT / "scripts" / "toolkit"

# ── 时间成本配置 ──
DECODE_TARGET_SECONDS = 60.0           # 单次解码目标耗时（秒）；全量枚举 ≥60 分钟由此与包数量决定
MIN_ATTACK_TOTAL_MINUTES = 60          # 模拟攻击全量解码预估下限（分钟）
SCRYPT_R, SCRYPT_KEYLEN = 8, 64
SCRYPT_N_LOG2_MAX = 20                 # n 上限 2^20（r=8 时内存 1GB）：Windows 下 maxmem 受 C long 约束，不能再高
SCRYPT_MAXMEM = (1 << 31) - 1          # 传给 hashlib.scrypt 的 maxmem（C long 安全上限）
# 构建期并行派生：每个派生任务峰值内存 ≈ 128*n*r 字节，并发数受内存约束；
# hashlib.scrypt 释放 GIL，线程池可真正并行（可用 XPAI_BUILD_WORKERS 覆盖）
DERIVE_WORKERS = max(1, int(os.environ.get("XPAI_BUILD_WORKERS", "3")))
PREWARM_SALT_COUNT = 72                # 预热盐池大小（覆盖全部真实包数量，不足时回退同步派生）


# ══════════════════════════════════════════════
#  scrypt 时间成本校准（n 受内存上限约束，不足部分用 p 线性补齐）
# ══════════════════════════════════════════════

def calibrate_scrypt():
    """实测本机 scrypt 基线耗时，先抬高 n（受内存上限），再用 p 补齐时间差。

    返回 (n, proj_decode_s)。p 写入全局 _P 并随每个包的头部下发。
    """
    global _P
    t0 = time.perf_counter()
    hashlib.scrypt(b"xpai-cal", salt=b"xpai-cal", n=2 ** 13, r=SCRYPT_R,
                   p=1, dklen=SCRYPT_KEYLEN, maxmem=SCRYPT_MAXMEM)
    base = max(time.perf_counter() - t0, 1e-6)
    n_log2 = min(SCRYPT_N_LOG2_MAX,
                 int(13 + max(0.0, math.log2(DECODE_TARGET_SECONDS / base))))
    n = 2 ** n_log2
    proj_n = base * (n / (2 ** 13))
    _P = max(1, min(255, round(DECODE_TARGET_SECONDS / max(proj_n, 1e-6))))
    proj = proj_n * _P
    mem_mb = 128 * n * SCRYPT_R // (1024 * 1024)
    print("  校准：基线(n=2^13) %.3fs → n=2^%d p=%d，单次解码预估 %.0fs，峰值内存约 %dMB"
          % (base, n_log2, _P, proj, mem_mb))
    return n, proj


# ══════════════════════════════════════════════
#  打包与内联解码表达式
#  打包(构建期)：salt 随机 → scrypt(salt) 派生密钥 → 密钥流 XOR → 乱序置换
#  解码(运行时)：内联表达式完成全部步骤，结果缓存进 sys 上的随机属性
#  模块属性中不残留任何解码函数/三元组结构
# ══════════════════════════════════════════════

_BUILD_KEY_CACHE = {}                  # 构建期派生缓存：salt → 密钥（避免重复付出 scrypt）
_P = 1                                 # 校准后的 scrypt p（时间线性放大，不增内存）
_SALT_POOL = []                        # 预热盐池：已提交并行派生的盐，打包时逐个取用
_KEY_FUTURES = {}                      # salt → 并行派生 Future（预热提交，取用时等待）
_KDF_EXECUTOR = None


def prewarm_derivation(count=PREWARM_SALT_COUNT):
    """预生成盐并提交线程池并行派生，与后续混淆流程重叠执行。

    没有预热时每次打包同步付一次完整派生（≈单次解码耗时），
    混淆阶段总时长 ≈ 真实包数 × 单次解码 / 并行度。
    """
    global _KDF_EXECUTOR
    _KDF_EXECUTOR = ThreadPoolExecutor(max_workers=DERIVE_WORKERS,
                                       thread_name_prefix="xpai-kdf")
    for _ in range(count):
        salt = bytes(random.getrandbits(8) for _ in range(16))
        _SALT_POOL.append(salt)
        _KEY_FUTURES[salt] = _KDF_EXECUTOR.submit(
            hashlib.scrypt, salt, salt=salt, n=_N, r=SCRYPT_R, p=_P,
            dklen=SCRYPT_KEYLEN, maxmem=SCRYPT_MAXMEM)
    print("  密钥预热：%d 个盐已提交 %d 线程并行派生（与混淆重叠执行）"
          % (count, DERIVE_WORKERS))


def _next_salt() -> bytes:
    """优先取预热盐（派生已在后台进行）；耗尽则现生成（同步派生兑底）。"""
    if _SALT_POOL:
        return _SALT_POOL.pop()
    return bytes(random.getrandbits(8) for _ in range(16))


def _derive_key_build(salt: bytes) -> bytes:
    k = _BUILD_KEY_CACHE.get(salt)
    if k is None:
        fut = _KEY_FUTURES.get(salt)
        if fut is not None:
            k = fut.result()                       # 预热命中：等待后台派生完成（通常已就绪）
        else:
            k = hashlib.scrypt(salt, salt=salt, n=_N, r=SCRYPT_R, p=_P,
                               dklen=SCRYPT_KEYLEN, maxmem=SCRYPT_MAXMEM)
        _BUILD_KEY_CACHE[salt] = k
    return k


def _blob_pack(raw: bytes) -> bytes:
    """把 raw 打包为单一 bytes 包：magic|n_log2|r|p|salt(16)|乱序密文。

    打包后立即做往返自检（与运行时内联表达式语义一致），失败即抛错。
    """
    salt = _next_salt()
    key = _derive_key_build(salt)
    xored = bytes(raw[i] ^ key[i % len(key)] for i in range(len(raw)))
    # 置换由派生密钥确定性驱动（运行时用同一把密钥重演，无需随包存放）
    perm = list(range(len(raw)))
    random.Random(key).shuffle(perm)
    scrambled = bytes(xored[perm[i]] for i in range(len(raw)))
    pinv = [0] * len(raw)
    for i in range(len(raw)):
        pinv[perm[i]] = i
    # 往返自检：逆置换还原 → 密钥流 XOR，必须与原文一致（运行时表达式做同样运算）
    recovered = bytes(scrambled[pinv[j]] ^ key[j % len(key)] for j in range(len(raw)))
    if recovered != raw:
        raise RuntimeError("打包往返自检失败，已中止（不会写入任何内容）")
    return (b"X\x1b" + bytes([_N_LOG2, SCRYPT_R, _P]) + salt + scrambled)


def _blob_repr(b: bytes) -> str:
    return 'b"' + "".join("\\x%02x" % x for x in b) + '"'


def _decode_expr(blob_name: str, ctx) -> str:
    """自包含内联解码表达式（纯表达式，不依赖任何模块级解码函数）。

    展开后：查缓存（setdefault 保证返回解码值本身）→ scrypt 派生
    （XPAI_VERIFY/XPAI_DECODE_N 可覆盖成本）→ 用派生密钥确定性重演置换求逆置换
    → 密钥流 XOR → 写缓存。密钥固定 dklen=64 循环使用，与构建期打包语义逐字节一致。
    依赖的 os/hashlib/random/sys 全部通过引导块注入的随机别名导入，不依赖模块自身导入。
    """
    o, h, rnd = ctx["os_a"], ctx["h_a"], ctx["r_a"]
    n_expr = ("(1<<((int({O}.environ['XPAI_DECODE_N']) if "
              "{O}.environ.get('XPAI_DECODE_N','').isdigit() else 0) "
              "or (10 if {O}.environ.get('XPAI_VERIFY')=='1' else 0) "
              "or __L))").replace("{O}", o)
    scrypt = ("__H__.scrypt(__s,salt=__s,n=" + n_expr +
              ",r=__r,p=__p,dklen=" + str(SCRYPT_KEYLEN) +
              ",maxmem=" + str(SCRYPT_MAXMEM) + ")").replace("__H__", h)
    core = "bytes(__k[__j%len(__k)]^__b[21+__q[__j]] for __j in range(len(__b)-21))"
    # 逆置换：与构建期同一 seed 重演 shuffle，再按值排序得到逆变换（纯表达式，无循环语句）
    q_call = ("(lambda __rng={R}.Random(__k),__pl=list(range(len(__b)-21)):"
              "(__rng.shuffle(__pl),sorted(range(len(__b)-21),key=__pl.__getitem__))[1])()"
              ).replace("{R}", rnd)
    k_call = "(lambda __k=" + scrypt + ":(lambda __q=" + q_call + ":" + core + ")())()"
    s_call = ("(lambda __s=__b[5:21],__L=__b[2],__r=__b[3],__p=__b[4]:" + k_call + ")()")
    body = "__c[__b] if __b in __c else __c.setdefault(__b," + s_call + ")"
    c_call = "(lambda __c=" + ctx["cache"] + ":" + body + ")()"
    return "(lambda __b:" + c_call + ")(" + blob_name + ")"


# ══════════════════════════════════════════════
#  源码切分与敏感发现
# ══════════════════════════════════════════════

def _split_triples(text: str):
    """把源码切分为 (是否三引号区块, 文本) 序列——三引号内容（文档字符串）不参与混淆。"""
    parts = []
    pos = 0
    for m in re.finditer(r'("""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\')', text):
        parts.append((False, text[pos:m.start()]))
        parts.append((True, m.group(0)))
        pos = m.end()
    parts.append((False, text[pos:]))
    return parts


def _discover_sensitive(text: str):
    """按特征模式从代码区（不含三引号区块）找出敏感明文字面量（去重、保序）。

    前瞻 (?<![A-Za-z0-9_]) 排除 f"/b"/r" 等前缀字符串——f-string 内的
    协议片段由专门的结构补丁处理，不能当普通字面量替换。
    """
    found = []

    def add(s):
        if s and s not in found:
            found.append(s)

    # 1) SK_SETTING_* 命令名（带引号的字面量）
    for m in re.findall(r'(?<![A-Za-z0-9_])(["\'])((?:SK_SETTING_)[A-Z0-9_]{2,})\1', text):
        add(m[1])
    # 2) 含厂商端点特征的字符串
    for m in re.findall(r'(?<![A-Za-z0-9_])(["\'])([^"\'\\\n]*xiaopaitech[^"\'\\\n]*)\1', text):
        add(m[1])
    # 3) 云端授权 URL
    for m in re.findall(r'(?<![A-Za-z0-9_])(["\'])(https://[^"\']*skyworthdigitaliot[^"\']*)\1', text):
        add(m[1])
    # 4) 固定 User-Agent 字面量
    for m in re.findall(r'(?<![A-Za-z0-9_])(["\'])(skyworth|Xiaopaitech NVR/1\.0)\1', text):
        add(m[1])
    return found


# 需要重命名的敏感常量名（仅限模块内部使用；被跨模块 import 的会自动跳过）
_SENSITIVE_NAMES = [
    "SK_TCP_PATH", "_SK_AUTH_KEY", "SK_RTSP_USER_AGENT", "SK_ALM_TOPIC_MAP",
    "_CLOUD_AUTH_URL", "_CLOUD_AUTH_CHECK_URL", "_CLOUD_AUTH_POLL_URL",
]


def _rand_name(prefix="_"):
    return prefix + "".join(random.choice("abcdefghijklmnopqrstuvwxyz0123456789")
                            for _ in range(8))


def _collect_imported_names(sources):
    """扫描全部源文件的 import/from 语句，收集跨模块引用的名字（重命名禁区）。"""
    imported = set()
    for src in sources:
        text = src.read_text(encoding="utf-8")
        for m in re.finditer(r'^\s*from\s+[.\w]+\s+import\s+(.+)$', text, re.MULTILINE):
            for part in m.group(1).split(","):
                tok = part.strip().split("(")[0].strip()
                name = tok.split(" as ")[0].strip()
                if name:
                    imported.add(name)
    return imported


def _rename_sensitive(text: str, imported_names):
    """敏感常量名 → 随机无意义标识符（同模块引用同步替换）。返回 (text, alias 映射)。"""
    aliases = {}
    for name in _SENSITIVE_NAMES:
        if name in imported_names:
            continue                                   # 跨模块导入，改名会断链
        if re.search(r'(?<![\w.])' + name + r'(?!\w)', text):
            alias = _rand_name()
            while alias in text:
                alias = _rand_name()
            text = re.sub(r'(?<![\w.])' + name + r'(?!\w)', alias, text)
            aliases[name] = alias
    return text, aliases


# ══════════════════════════════════════════════
#  替换与结构补丁（全部基于 blob 别名 + 内联解码表达式）
# ══════════════════════════════════════════════

def _substitute_literals(text: str, sensitives, blobs, ctx):
    """所有带引号的敏感字面量出现处 → 内联解码表达式（.decode() 还原 str）。"""
    for plain in sensitives:
        esc = re.escape(plain)
        blob = blobs[plain]
        expr = _decode_expr(blob, ctx) + ".decode()"
        text = re.sub(r'(?<![A-Za-z0-9_])(["\'])' + esc + r'\1', lambda m, e=expr: e, text)
    return text


def _rewrite_definitions(text: str, sensitives, packed_map):
    """模块级定义 NAME = "PLAIN" → NAME = b"..."（单一 bytes 包，无结构指纹）。"""
    for plain in sensitives:
        esc = re.escape(plain)
        packed = packed_map[plain]
        text = re.sub(
            r'^([A-Za-z_]\w*) = (["\'])' + esc + r'\2[ \t]*(#.*)?$',
            lambda m, b=packed: '%s = %s' % (m.group(1), _blob_repr(b)),
            text, flags=re.MULTILINE)
    return text


def _obfuscate_auth_key(text: str, aliases, ctx):
    """KEY 字节数组（可能跨行）→ 指向 blob 别名；使用处内联解码。"""
    ak = aliases.get("_SK_AUTH_KEY")
    if ak is None:
        return text
    m = re.search(re.escape(ak) + r'\s*=\s*bytes\(\[([^\]]*)\]\)', text)
    if m:
        raw = bytes(int(x.strip(), 0) for x in m.group(1).split(',') if x.strip())
        blob = _rand_name()
        ctx["blobs"]["<AUTH_KEY_BYTES>"] = blob
        text = (text[:m.start()] + blob + ' = ' + _blob_repr(_blob_pack(raw)) +
                '\n' + ak + ' = ' + blob + text[m.end():])
    out = []
    def_line = re.compile(r'\s*' + re.escape(ak) + r'\s*=\s*')
    blob_line = re.compile(r'\s*' + re.escape(ak) + r'\s*=\s*[A-Za-z_]\w*\s*$')
    for line in text.splitlines(keepends=True):
        if def_line.match(line) or blob_line.match(line):
            out.append(line)                       # 定义行不动
        elif ak in line:
            out.append(line.replace(ak, _decode_expr(ctx["blobs"]["<AUTH_KEY_BYTES>"], ctx)))
        else:
            out.append(line)
    return ''.join(out)


def _patch_query_functions(text: str, ctx, path_blob):
    """SK HTTP URL 的端点片段 → 指向 path_blob 的内联解码（需在字面量替换前执行）。"""
    if not path_blob:
        return text
    return re.sub(
        r'url = f"http://\{host\}:\{port\}(/[^"\n]+)"',
        lambda m: 'url = f"http://{host}:{port}" + '
                  + _decode_expr(path_blob, ctx) + '.decode()',
        text)


def _patch_discovery_header(text: str, aliases, ctx):
    """discovery 的 HTTP 头构造块：端点与 UA 就地解码。"""
    if 'header = (' not in text:
        return text
    path_alias = aliases.get("SK_TCP_PATH")
    if not path_alias:
        return text
    ua_blob = _rand_name()
    ctx["blobs"]["<UA_BLOB>"] = ua_blob
    ua_expr = _decode_expr(ua_blob, ctx) + ".decode()"
    path_expr = _decode_expr(path_alias, ctx) + ".decode()"
    # f-string 字段内表达式含花括号，必须加括号包裹避免被解析为嵌套替换字段；
    # UA 包在函数内定义（不留模块属性，进一步缩小扫描面）
    locals_block = ('    %s = %s\n'
                    '    _tcp_path = (%s)\n'
                    '    _tcp_ua = (%s)\n'
                    % (ua_blob, _blob_repr(_blob_pack(b"Xiaopaitech NVR/1.0")),
                       path_expr, ua_expr))
    text = re.sub(r'^( *)(header = \()',
                  lambda m: locals_block.replace('    ', m.group(1) or '    ')
                            + m.group(1) + m.group(2),
                  text, count=1, flags=re.MULTILINE)
    text = text.replace('{' + path_alias + '}', '{_tcp_path}')
    text = re.sub(r'User-Agent: Xiaopaitech NVR/1\.0', 'User-Agent: {_tcp_ua}', text)
    return text


def _patch_events(text: str, aliases, ctx):
    """events：UA 在 f-string 中的使用 + 报警码映射表。"""
    ua_alias = aliases.get("SK_RTSP_USER_AGENT")
    if ua_alias:
        # f-string 字段内表达式含花括号，必须加括号包裹避免被解析为嵌套替换字段
        text = text.replace('{' + ua_alias + '}',
                            '{(' + _decode_expr(ua_alias, ctx)
                            + '.decode())}')
    map_alias = aliases.get("SK_ALM_TOPIC_MAP")
    if not map_alias:
        return text
    m = re.search(re.escape(map_alias) + r'\s*=\s*\{(.*?)\n\}', text, re.DOTALL)
    if m:
        pairs = re.findall(r'["\']([A-Z]{2,4})["\']\s*:\s*["\']([a-z_]+)["\']', m.group(1))
        if pairs:
            # 报警码键逐个打包；映射表变成 (bytes 包, topic) 对，结构与诱饵一致
            lines = []
            for k, v in pairs:
                blob = _rand_name()
                ctx["blobs"]["<ALM:" + k + ">"] = blob
                lines.append('    (%s, "%s"),' % (_blob_repr(_blob_pack(k.encode("utf-8"))), v))
            text = (text[:m.start()] + map_alias + ' = (\n' + "\n".join(lines) + '\n)'
                    + text[m.end():])
            # 归一化函数改为逐条解码比对（进程级缓存保证同一包只付一次时间成本）
            text = re.sub(
                r'return ' + re.escape(map_alias)
                + r'\.get\(\(alm or ""\)\.strip\(\)\.upper\(\), \(alm or "unknown"\)\.lower\(\)\)',
                '_k = (alm or "").strip().upper()\n'
                '    for _bt, _tp in ' + map_alias + ':\n'
                '        if _k == ' + _decode_expr("_bt", ctx)
                + '.decode():\n'
                '            return _tp\n'
                '    return (alm or "unknown").lower()',
                text)
    return text


def _patch_cloud_urls(text: str, aliases, ctx):
    """device_mgmt：云端授权 URL 常量的使用处内联解码。"""
    url_alias = aliases.get("_CLOUD_AUTH_URL")
    chk_alias = aliases.get("_CLOUD_AUTH_CHECK_URL")
    if url_alias:
        text = re.sub(r'(_requests_lib\.post\(\s*\n\s*)' + re.escape(url_alias) + r',',
                      r'\1' + _decode_expr(url_alias, ctx) + '.decode(),',
                      text)
    if chk_alias:
        text = re.sub(r'(_CLOUD_AUTH_POLL_URL or )' + re.escape(chk_alias) + r'\b',
                      r'\1' + _decode_expr(chk_alias, ctx) + '.decode()',
                      text)
    return text


def _inject_bootstrap(text: str, ctx):
    """注入 os/hashlib/random/sys 别名导入 + 进程级解码缓存（藏于 sys 的随机属性名）。"""
    m = re.match(r'\A\s*(?:"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\')\s*\n?', text)
    pos = m.end() if m else 0
    block = ("\nimport os as %s\n"
             "import hashlib as %s\n"
             "import random as %s\n"
             "import sys as %s\n"
             "if not hasattr(%s, %r):\n"
             "    setattr(%s, %r, {})\n"
             "%s = getattr(%s, %r)\n" % (ctx["os_a"], ctx["h_a"], ctx["r_a"],
                                          ctx["sys"], ctx["sys"], ctx["cache_key"],
                                          ctx["sys"], ctx["cache_key"],
                                          ctx["cache"], ctx["sys"], ctx["cache_key"]))
    return text[:pos] + block + text[pos:]


# ══════════════════════════════════════════════
#  诱饵注入
# ══════════════════════════════════════════════

def _make_junk_line() -> str:
    return '%s = %s\n' % (_rand_name(), _blob_repr(_make_junk_blob()))


def _append_blob_lines(text: str, lines) -> str:
    """把 blob 赋值行插入文件（若有 __main__ 守卫则插在其前，保证导入时可见）。"""
    m = re.search(r'^if __name__\s*==', text, re.MULTILINE)
    block = "".join(lines)
    if m:
        return text[:m.start()] + block + "\n" + text[m.start():]
    return text + "\n" + block


def inject_decoys(text: str):
    """注入结构相同的假包（单一 bytes，解码后为无语义垃圾），真假不可区分。"""
    real = _count_blobs(text)
    n = max(2, int(real * 1.2)) if real else 2
    return _append_blob_lines(text, [_make_junk_line() for _ in range(n)])


def _make_junk_blob() -> bytes:
    """假包：头部参数与真实包完全一致，密文区纯随机。

    诱饵解码出来本就是无语义垃圾，构建期无需派生密钥（零成本）；
    攻击者按头部参数解码时照样付出完整时间成本——这正是诱饵的目的。
    """
    data_len = random.randint(10, 40)
    salt = bytes(random.getrandbits(8) for _ in range(16))
    junk_ct = bytes(random.getrandbits(8) for _ in range(data_len))
    return b"X\x1b" + bytes([_N_LOG2, SCRYPT_R, _P]) + salt + junk_ct


def _count_blobs(text: str) -> int:
    """统计文本中已打包的 bytes 常量数量（真实+诱饵）。"""
    return len(re.findall(r'= b"\\x58\\x1b', text))


# 全量枚举成本下限所需的包总数（单次解码≈DECODE_TARGET_SECONDS 时）
MIN_BLOB_COUNT = max(1, int(MIN_ATTACK_TOTAL_MINUTES * 60 / DECODE_TARGET_SECONDS))


def pad_decoys(sources):
    """全局补齐诱饵，使包总数 ≥ MIN_BLOB_COUNT（保证全量枚举成本下限）。"""
    total = sum(_count_blobs(s.read_text(encoding='utf-8')) for s in sources)
    added = 0
    while total < MIN_BLOB_COUNT:
        target = random.choice(sources)
        text = target.read_text(encoding='utf-8')
        text = _append_blob_lines(text, [_make_junk_line()])
        compile(text, str(target), 'exec')
        target.write_text(text, encoding='utf-8')
        total += 1
        added += 1
    return added


# ══════════════════════════════════════════════
#  残留扫描（fail-closed）
# ══════════════════════════════════════════════

_RESIDUAL_RULES = [
    (r'SK_SETTING_[A-Z0-9_]{2,}', 'SK 命令名'),
    (r'xiaopaitech', '厂商端点'),
    (r'skyworthdigitaliot', '云端域名'),
    (r'skyworth', 'UA/厂商标识'),
    (r'0x72\s*,\s*0x58', 'KEY 原始字节'),
    (r'["\'](MD|MP|HD|VGR|VGL|VS|VD|HTD|LTD)["\']', '报警码'),
]


def _assert_clean(text: str, label: str):
    """fail-closed：去除 docstring 与注释后扫描残留敏感内容。"""
    stripped = re.sub(r'("""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\')', ' ', text)
    stripped = "\n".join(line.split('#', 1)[0] for line in stripped.splitlines())
    for pattern, name in _RESIDUAL_RULES:
        hit = re.search(pattern, stripped, re.IGNORECASE)
        if hit:
            raise RuntimeError('%s 混淆后仍残留「%s」: %r' % (label, name, hit.group(0)))


def obfuscate_file(path: Path, imported_names):
    text = path.read_text(encoding='utf-8')
    ctx = {
        "cache": _rand_name("__"),
        "cache_key": _rand_name("_xk_"),
        "sys": _rand_name("_s"),
        "os_a": _rand_name("_o"),
        "h_a": _rand_name("_h"),
        "r_a": _rand_name("_r"),
        "blobs": {},
    }
    parts = _split_triples(text)
    code_only = "".join(chunk for is_t, chunk in parts if not is_t)
    sensitives = _discover_sensitive(code_only)

    # 每个敏感字面量一个独立随机别名 + 独立打包（逐包独立 salt/密钥/乱序）
    blobs = {}
    packed_map = {}
    for plain in sensitives:
        blobs[plain] = _rand_name()
        packed_map[plain] = _blob_pack(plain.encode("utf-8"))   # 内含往返自检
        ctx["blobs"][plain] = blobs[plain]

    # URL 端点包：优先复用已发现的端点字面量；否则（如 ptz：端点在 f-string 中）
    # 专用打包一份，并补上包定义行。URL 补丁必须在字面量替换前执行（依赖 f-string 中的原始片段）。
    path_blob = None
    if "/xiaopaitech/device_service" in blobs:
        path_blob = blobs["/xiaopaitech/device_service"]
    elif re.search(r'url = f"http://\{host\}:\{port\}/', text):
        path_blob = _rand_name()
        ctx["blobs"]["<PATH_BLOB>"] = path_blob
        packed_map["<PATH_BLOB>"] = _blob_pack(b"/xiaopaitech/device_service")
        text = _append_blob_lines(
            text, ['%s = %s\n' % (path_blob, _blob_repr(packed_map["<PATH_BLOB>"]))])
    text = _patch_query_functions(text, ctx, path_blob)
    parts = _split_triples(text)          # URL 补丁后重新切分，保证补丁结果进入后续管线

    # 模块级定义先转成 blob 赋值（此时仍用原始常量名，稍后随重命名），
    # 再把其余带引号出现处替换为内联解码表达式。
    new_parts = []
    for is_t, chunk in parts:
        if is_t:
            new_parts.append(chunk)            # 文档字符串：编译时整体剥离，不动
            continue
        chunk = _rewrite_definitions(chunk, sensitives, packed_map)
        chunk = _substitute_literals(chunk, sensitives, blobs, ctx)
        new_parts.append(chunk)
    text = "".join(new_parts)

    # 敏感常量名重命名为无意义标识符（结构补丁以别名为准）
    text, aliases = _rename_sensitive(text, imported_names)

    text = _obfuscate_auth_key(text, aliases, ctx)
    text = _patch_discovery_header(text, aliases, ctx)
    text = _patch_events(text, aliases, ctx)
    text = _patch_cloud_urls(text, aliases, ctx)

    if ctx["cache"] in text:
        text = _inject_bootstrap(text, ctx)    # 有解码表达式才注入别名导入与缓存引导
    _assert_clean(text, path.name)
    compile(text, str(path), 'exec')           # 语法自检，改坏立即暴露
    path.write_text(text, encoding='utf-8')
    return len(sensitives)


# ══════════════════════════════════════════════
#  编译
# ══════════════════════════════════════════════

def compile_all(sources):
    from Cython.Build import cythonize
    from setuptools import Distribution, Extension
    from setuptools.command.build_ext import build_ext

    py_lib = "python{}{}".format(sys.version_info.major, sys.version_info.minor)

    ext_modules = []
    for src in sources:
        if src.stem == "__init__":
            name = "scripts.toolkit"
        else:
            name = "scripts.toolkit." + src.stem
        ext_modules.append(
            Extension(
                name,
                sources=[src.relative_to(ROOT).as_posix()],
                libraries=[py_lib],
                library_dirs=[str(Path(sys.prefix) / "libs")],
                extra_link_args=["-static-libgcc"],
            )
        )

    # 剥离全部文档字符串与函数签名（docstrings 是 Cython 全局选项）
    from Cython.Compiler import Options as _cython_options
    _cython_options.docstrings = False
    ext_modules = cythonize(
        ext_modules,
        compiler_directives={
            "language_level": "3",
            "embedsignature": False,
            "annotation_typing": False,
        },
    )

    dist = Distribution({"ext_modules": ext_modules})
    cmd = build_ext(dist)
    cmd.inplace = True
    cmd.compiler = "mingw32"
    cmd.ensure_finalized()
    cmd.run()

    # __init__ 模块会被 setuptools 输出到包目录外，移回包内
    suffix = sysconfig.get_config_var("EXT_SUFFIX")
    wrong_place = ROOT / "scripts" / ("toolkit" + suffix)
    if wrong_place.exists():
        shutil.move(str(wrong_place), str(TOOLKIT_DIR / ("__init__" + suffix)))


# ══════════════════════════════════════════════
#  验证（纯 .pyd 状态 + 模拟 agent 攻击）
# ══════════════════════════════════════════════

VERIFY_CODE = '''
import importlib, os, pkgutil, re, time
import scripts.toolkit as tk
assert not tk.__doc__, "toolkit __init__ docstring 未剥离"

bad, blobs_total = [], 0
for _mi in pkgutil.iter_modules(tk.__path__):
    _m = importlib.import_module("scripts.toolkit." + _mi.name)
    if _m.__doc__:
        bad.append(_m.__name__ + ".__doc__")

    # 1) 字符串属性残留扫描（解码入口/敏感明文不应出现在模块属性中）
    for _k, _v in vars(_m).items():
        if isinstance(_v, str) and re.search("sk_setting|xiaopaitech|skyworth", _v, re.I):
            bad.append("str-leak:" + _m.__name__ + "." + _k)
        if isinstance(_v, (list, tuple)):
            for _it in _v:
                if isinstance(_it, str) and re.search("sk_setting|xiaopaitech|skyworth", _it, re.I):
                    bad.append("seq-leak:" + _m.__name__ + "." + _k)

    # 2) 模拟攻击：按名字语义寻找解码函数（应一无所获）
    for _k, _v in vars(_m).items():
        if callable(_v) and re.search(r"(?i)dec|decode|decrypt|xor|unscramble|secret|obfusc", _k):
            bad.append("decoder-entry:" + _m.__name__ + "." + _k)

    # 3) 指纹扫描：单一 bytes 属性即候选包（真假必须混在一起）
    for _k, _v in vars(_m).items():
        if isinstance(_v, bytes) and len(_v) >= 24:
            blobs_total += 1
assert not bad, "安全检查失败: %s" % bad
assert blobs_total > 0, "未发现任何打包常量"

# 4) 逻辑回归（XPAI_VERIFY=1 快速模式下解码为毫秒级）
try:
    from scripts.toolkit.events import _normalize_private_topic
    assert _normalize_private_topic("MD") == "motion"
    assert _normalize_private_topic("HD") == "human"
    assert _normalize_private_topic("XX") == "xx"
except ImportError:
    pass

# 5) 抽样解码耗时（快速模式），并按校准参数推算攻击总成本
_m0 = importlib.import_module("scripts.toolkit." + pkgutil.iter_modules(tk.__path__)[0].name)
_sample = next(_v for _v in vars(_m0).values() if isinstance(_v, bytes) and len(_v) >= 24)
_t0 = time.time()
import hashlib as _h
_L, _r, _p, _salt = _sample[2], _sample[3], _sample[4], _sample[5:21]
_n_smp = 10 if os.environ.get("XPAI_VERIFY") == "1" else max(_L, 10)
_h.scrypt(_salt, salt=_salt, n=1 << _n_smp, r=_r, p=_p,
          dklen=64, maxmem=(1 << 31) - 1)
_t1 = time.time()
_proj_min = float(os.environ.get("XPAI_PER_DECODE_S", "60"))
_proj_total = _proj_min * blobs_total / 60.0
assert _proj_total >= _proj_min, \\
    "预估攻击总时长 %.0f 分钟 < 目标 %.0f 分钟（包数 %d）" % (_proj_total, _proj_min, blobs_total)

# 正式工具包（8 个子模块）强校验导出数量
if len([m for m in pkgutil.iter_modules(tk.__path__)]) >= 8:
    assert len(tk.__all__) == 67, "__all__ 数量异常"
print("verify ok: blobs=%d, 抽样快速解码 %.3fs, 预估全量攻击 %.0f 分钟"
      % (blobs_total, _t1 - _t0, _proj_total))
'''

BINARY_SCAN_KEYWORDS = [b"SK_SETTING", b"xiaopaitech", b"skyworth", b"Skyworth",
                        b"GET_MAGIC", b"skyworthdigitaliot", b"Xiaopaitech"]


def binary_scan():
    hits = []
    for pyd in TOOLKIT_DIR.glob("*.pyd"):
        data = pyd.read_bytes()
        for kw in BINARY_SCAN_KEYWORDS:
            if kw in data:
                hits.append((pyd.name, kw.decode()))
    return hits


def verify_import():
    env = dict(os.environ)
    env["XPAI_VERIFY"] = "1"
    env["XPAI_PER_DECODE_S"] = str(int(DECODE_TARGET_SECONDS))
    r = subprocess.run([sys.executable, "-c", VERIFY_CODE], cwd=str(ROOT), env=env)
    return r.returncode == 0


def cleanup_intermediates():
    for c_file in TOOLKIT_DIR.glob("*.c"):
        c_file.unlink()
    pycache = TOOLKIT_DIR / "__pycache__"
    if pycache.is_dir():
        shutil.rmtree(pycache)
    build_dir = ROOT / "build"
    if build_dir.is_dir():
        shutil.rmtree(build_dir)


def cleanup_old_artifacts():
    """构建前清理旧的 .pyd / 缓存，避免残留干扰新构建与验证。"""
    for pyd in TOOLKIT_DIR.glob("*.pyd"):
        pyd.unlink()
    pycache = TOOLKIT_DIR / "__pycache__"
    if pycache.is_dir():
        shutil.rmtree(pycache)
    spycache = (ROOT / "scripts") / "__pycache__"
    if spycache.is_dir():
        shutil.rmtree(spycache)


# ══════════════════════════════════════════════
#  主流程
# ══════════════════════════════════════════════

# 校准后的全局参数（obfuscate_file 使用）
_N = 2 ** 16
_N_LOG2 = 16


def main():
    global _N, _N_LOG2
    if not TOOLKIT_DIR.is_dir():
        print("未找到 scripts/toolkit/ 目录——请在项目根目录下运行（build.bat 会自动处理）。")
        return 1

    sources = sorted(TOOLKIT_DIR.glob("*.py"))
    if not sources:
        print("toolkit 中没有待编译的 .py 文件，无需处理。")
        return 0

    print("待处理文件（共 %d 个）：" % len(sources))
    for src in sources:
        print("  - " + src.name)

    cleanup_old_artifacts()

    print("\n[0/4] 校准 scrypt 时间成本（目标单次解码 %.0fs）..." % DECODE_TARGET_SECONDS)
    _N, proj_s = calibrate_scrypt()
    _N_LOG2 = int(round(math.log2(_N)))
    prewarm_derivation()    # 真实包密钥后台并行派生，与 [1/4] 混淆重叠执行

    imported_names = _collect_imported_names(sources)

    print("\n[1/4] 混淆敏感常量（独立打包 + 内联解码 + 重命名 + 诱饵）...")
    try:
        for src in sources:
            n = obfuscate_file(src, imported_names)
            text = src.read_text(encoding='utf-8')
            text = inject_decoys(text)
            compile(text, str(src), 'exec')
            src.write_text(text, encoding='utf-8')
            print("  %s: 处理 %d 个敏感字面量，自检+残留扫描通过" % (src.name, n))
        added = pad_decoys(sources)
        if added:
            print("  全局补齐诱饵 %d 个（包总数下限 %d，保证全量枚举 ≥%d 分钟）"
                  % (added, MIN_BLOB_COUNT, MIN_ATTACK_TOTAL_MINUTES))
    except Exception as e:
        print("\n混淆失败：%s" % e)
        print("源码保持原样（如已被部分改写，请从备份重新拷入），未编译任何内容。")
        return 1

    print("\n[2/4] 编译中 ...")
    try:
        compile_all(sources)
    except Exception as e:
        print("\n编译失败：%s" % e)
        print("源码未删除，请从备份重新拷入后重试。")
        return 1

    print("\n[3/4] 验证（纯 .pyd 状态 + 模拟攻击）...")
    hits = binary_scan()
    if hits:
        print("二进制明文扫描命中：%s" % hits)
        print("验证失败！源码已恢复前状态不可用，请从备份重新拷入排查。")
        return 1
    tmp_dir = ROOT / "_src_tmp"
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)
    tmp_dir.mkdir()
    for src in sources:
        shutil.move(str(src), str(tmp_dir / src.name))
    try:
        ok = verify_import()
    except Exception:
        ok = False
    if not ok:
        for f in tmp_dir.iterdir():
            shutil.move(str(f), str(TOOLKIT_DIR / f.name))
        shutil.rmtree(tmp_dir)
        print("导入验证失败！源码已恢复到 toolkit/（混淆后版本），请排查。")
        return 1

    print("\n[4/4] 删除源码与中间产物 ...")
    for f in sorted(tmp_dir.iterdir()):
        f.unlink()
        print("  已删除 scripts/toolkit/" + f.name)
    shutil.rmtree(tmp_dir)
    cleanup_intermediates()
    print("\n完成：toolkit 已以受保护的 .pyd 形式提供。")
    print("提示：单次解码约 %.0fs；XPAI_VERIFY=1 可启用快速模式（仅调试）。" % proj_s)
    return 0


if __name__ == "__main__":
    sys.exit(main())
