import ctypes
import hashlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import sysconfig
import tempfile


PACKAGE = "camera-proto"
MANIFEST = Path(__file__).resolve().with_name("runtime_artifacts.json")
LIBRARIES = {
    "win_amd64": "camera_proto.dll",
    "linux_x86_64": "camera_proto.so",
    "macos_x86_64": "camera_proto.dylib",
    "macos_arm64": "camera_proto.dylib",
}
WHEEL_PLATFORMS = {
    "win_amd64": r"win_amd64",
    "linux_x86_64": r"manylinux(?:1|2010|2014|_[0-9]+_[0-9]+)_x86_64",
    "macos_x86_64": r"macosx_[0-9]+_[0-9]+_x86_64",
    "macos_arm64": r"macosx_[0-9]+_[0-9]+_arm64",
}


def _platform_key():
    if ctypes.sizeof(ctypes.c_void_p) != 8 or sys.version_info < (3, 10):
        raise RuntimeError("摄像头协议库需要 64 位 Python 3.10 或以上版本。")
    machine = platform.machine().lower()
    if sys.platform == "win32" and sysconfig.get_platform() == "win-amd64":
        return "win_amd64"
    if sys.platform == "linux" and machine in ("amd64", "x86_64"):
        if platform.libc_ver()[0] != "glibc":
            raise RuntimeError("Linux 协议库仅支持 glibc x64；不支持 musl/Alpine 或无法识别的 libc。")
        return "linux_x86_64"
    if sys.platform == "darwin":
        if machine == "x86_64":
            return "macos_x86_64"
        if machine == "arm64":
            return "macos_arm64"
    raise RuntimeError(
        f"不支持当前协议库平台：{sys.platform}/{machine}；"
        "仅支持 Windows x64、Linux glibc x64、macOS Intel/ARM64 的 64 位解释器。")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RuntimeError(f"本地固定产物清单包含重复字段：{key}。")
        result[key] = value
    return result


def _load_manifest():
    try:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    except (OSError, UnicodeError, ValueError) as exc:
        raise RuntimeError(f"无法读取本地固定产物清单 {MANIFEST}；请恢复随 Skill 交付的已审核清单。") from exc
    if not isinstance(manifest, dict) or set(manifest) != {"package", "version", "environment", "platforms"}:
        raise RuntimeError("本地固定产物清单结构无效：需要 package、version、environment、platforms。")
    if manifest["package"] != PACKAGE:
        raise RuntimeError(f"本地固定产物清单的 package 必须为 {PACKAGE}。")
    version = manifest["version"]
    environment = manifest["environment"]
    release = r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
    if (not isinstance(version, str) or not isinstance(environment, str)
            or environment not in ("production", "test")
            or re.fullmatch(release + (r"\.dev(?:0|[1-9][0-9]*)" if environment == "test" else ""), version) is None):
        raise RuntimeError("本地固定产物清单环境/版本不一致：production 需要正式 x.y.z，test 需要 x.y.z.devN。")
    platforms = manifest["platforms"]
    if not isinstance(platforms, dict) or not platforms or not set(platforms) <= set(LIBRARIES):
        raise RuntimeError("本地固定产物清单 platforms 无效或为空，仅允许四个已支持的平台键。")
    for key, artifact in platforms.items():
        if not isinstance(artifact, dict) or set(artifact) != {"wheel_filename", "wheel_sha256", "library", "resources"}:
            raise RuntimeError(f"本地固定产物清单 {key} 结构无效：缺少或存在未知产物字段。")
        library = LIBRARIES[key]
        resources = artifact["resources"]
        if (artifact["library"] != library or not isinstance(resources, dict)
                or set(resources) != {library, "cacert.pem"}):
            raise RuntimeError(f"本地固定产物清单 {key} 仅允许 {library} 和 cacert.pem，库名必须匹配平台。")
        filename = artifact["wheel_filename"]
        tag = WHEEL_PLATFORMS[key]
        pattern = rf"camera_proto-{re.escape(version)}-py3-none-{tag}(?:\.{tag})*\.whl"
        if not isinstance(filename, str) or re.fullmatch(pattern, filename) is None:
            raise RuntimeError(f"本地固定产物清单 {key} 的 wheel 文件名与包名、版本或平台不一致。")
        digests = [artifact["wheel_sha256"], *resources.values()]
        if any(not isinstance(digest, str) or re.fullmatch(r"[0-9a-fA-F]{64}", digest) is None for digest in digests):
            raise RuntimeError(f"本地固定产物清单 {key} 的 SHA256 必须为 64 位十六进制摘要。")
        artifact["wheel_sha256"] = artifact["wheel_sha256"].lower()
        artifact["resources"] = {name: digest.lower() for name, digest in resources.items()}
    return manifest


def _check_platform_version(key, wheel_filename):
    if key == "win_amd64":
        return
    if key == "linux_x86_64":
        system, version = "glibc", platform.libc_ver()[1]
    else:
        system, version = "macOS", platform.mac_ver()[0]
    match = re.fullmatch(r"([0-9]+)\.([0-9]+)(?:\.[0-9]+)*", version) if isinstance(version, str) else None
    if match is None:
        raise RuntimeError(
            f"无法解析宿主 {system} 版本：{version!r}；无法确认已审核 wheel 的最低系统要求；"
            "未运行 pip，未复制资源。")
    host_version = tuple(map(int, match.groups()))
    legacy = {"manylinux1": (2, 5), "manylinux2010": (2, 12), "manylinux2014": (2, 17)}
    minimums = []
    # 文件名及每个 platform tag 已由 _load_manifest 严格验证。
    for tag in wheel_filename[:-4].rsplit("-", 1)[1].split("."):
        fields = tag.split("_")
        minimums.append(legacy[fields[0]] if fields[0] in legacy
                        else (int(fields[1]), int(fields[2])))
    if not any(host_version >= minimum for minimum in minimums):
        required = ".".join(map(str, min(minimums)))
        raise RuntimeError(
            f"宿主 {system} 版本 {version} 过低；已审核 wheel {wheel_filename} "
            f"最低需要 {system} {required}；未运行 pip，未复制资源。")


def _matches(path, digest):
    return path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == digest


def _install(manifest, artifact):
    version = manifest["version"]
    print(f"正在通过当前 Python 安装 {PACKAGE}=={version}（{manifest['environment']}）……", file=sys.stderr)
    with tempfile.TemporaryDirectory(prefix="camera-proto-install-") as folder:
        requirements = Path(folder) / "requirements.txt"
        requirements.write_text(
            f"{PACKAGE}=={version} --hash=sha256:{artifact['wheel_sha256']}\n", encoding="utf-8")
        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "--isolated", "--disable-pip-version-check",
                 "install", "--index-url", "https://pypi.org/simple",
                 "--only-binary=:all:", "--no-deps", "--require-hashes", "--no-input",
                 "--timeout", "30", "--retries", "2", "-r", str(requirements)],
                check=True, timeout=300, stdout=sys.stderr, stderr=sys.stderr)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("协议库安装超时；请检查网络后重新运行准备脚本。") from exc
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(
                "协议库安装失败；请检查上方 pip 错误、网络和当前 Python 的安装权限。"
                f'如缺少 pip，请先运行 "{sys.executable}" -m ensurepip，再重试准备脚本。') from exc


def prepare_runtime():
    key = _platform_key()
    manifest = _load_manifest()
    artifact = manifest["platforms"].get(key)
    if artifact is None:
        raise RuntimeError(
            f"本地固定产物清单尚未配置 {key} 的已验证产物"
            f"（{PACKAGE}=={manifest['version']}，{manifest['environment']}）；"
            "产物待接入，请等待审核后的清单随 Skill 交付；未运行 pip。")
    _check_platform_version(key, artifact["wheel_filename"])
    resources = artifact["resources"]
    toolkit = Path(__file__).resolve().parent / "toolkit"
    if not toolkit.is_dir():
        raise RuntimeError(f"未找到 skill 的 toolkit 目录：{toolkit}；请保留完整 skill 目录结构。")
    if all(_matches(toolkit / name, digest) for name, digest in resources.items()):
        return toolkit

    try:
        distribution = metadata.distribution(PACKAGE)
    except metadata.PackageNotFoundError:
        _install(manifest, artifact)
        distribution = metadata.distribution(PACKAGE)
    if distribution.version != manifest["version"]:
        raise RuntimeError(
            f"当前 Python 已安装 {PACKAGE}=={distribution.version}，需要 {manifest['version']}；"
            "请为此 skill 使用独立虚拟环境，并用该环境的 Python 重新运行准备脚本，"
            "本脚本不会自动升级或降级已有依赖。")

    files = {path.as_posix(): path for path in distribution.files or ()}
    install_root = Path(distribution.locate_file("")).resolve()
    resource_dir = install_root / "camera_proto" / "lib"
    payloads = {}
    for name, digest in resources.items():
        entry = files.get(f"camera_proto/lib/{name}")
        if entry is None:
            raise RuntimeError(f"安装包缺少资源清单项 {name}；请在干净的虚拟环境重新运行准备脚本。")
        source = Path(distribution.locate_file(entry)).resolve()
        if source != resource_dir / name or not source.is_file():
            raise RuntimeError(f"安装包资源路径无效：{name}；请在干净的虚拟环境重新运行准备脚本。")
        payload = source.read_bytes()
        if hashlib.sha256(payload).hexdigest() != digest:
            raise RuntimeError(f"安装包资源 SHA256 校验失败：{name}；未复制，请在干净的虚拟环境重试。")
        if not _matches(toolkit / name, digest):
            payloads[name] = payload

    with tempfile.TemporaryDirectory(prefix=".camera-proto-", dir=toolkit) as folder:
        staging = Path(folder)
        for name, payload in payloads.items():
            (staging / name).write_bytes(payload)
        for name in payloads:
            os.replace(staging / name, toolkit / name)

    if not all(_matches(toolkit / name, digest) for name, digest in resources.items()):
        raise RuntimeError("落地文件校验失败；请停止其他准备操作后重新运行本脚本。")
    return toolkit


def main():
    try:
        toolkit = prepare_runtime()
    except (OSError, RuntimeError, metadata.PackageNotFoundError) as exc:
        print(f"协议库准备失败：{exc}", file=sys.stderr)
        if isinstance(exc, OSError):
            print("请检查目录权限；如原生库被占用，请先正常关闭使用该 skill 的 MCP 服务，再重试。"
                  "已落地的文件会在重试时检查并补齐。", file=sys.stderr)
        return 1
    print(f"协议库已就绪：{toolkit}（原生库与 CA 均已按本地固定产物清单校验）", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
