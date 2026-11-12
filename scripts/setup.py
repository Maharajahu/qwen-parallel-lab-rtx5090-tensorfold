"""Prepare the pinned Windows x64 experiments without starting inference."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".runtime"
VARIANTS = ("fanout", "shared-context")
OMP_VERSION = "18.18.8"
OMP_COMMIT = "679691a78141de0dd6ba1b7a5d5c1b1d7d967a63"
OMP_SHA256 = "88fe3410b3daefd7435a5915805563f3f9058ad1841de622f40bd4247601072a"
OMP_BYTES = 250181120
OMP_API = f"https://build.stencil.so/api/products/omp/versions/{OMP_VERSION}/windows-x86_64"


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def checked_child(root, relative):
    """Reject manifest paths that could escape their model/source directory."""
    root = Path(root).resolve()
    child = (root / relative).resolve()
    if child == root or not child.is_relative_to(root):
        raise ValueError(f"Path escapes its directory: {relative}")
    return child


def verify_file(path, expected_hash, size=None):
    path = Path(path)
    if size is not None and path.stat().st_size != size:
        raise ValueError(f"Size mismatch: {path}")
    if not re.fullmatch(r"[0-9a-f]{64}", expected_hash or ""):
        raise ValueError(f"Missing or invalid SHA256 for {path}")
    if sha256(path) != expected_hash:
        raise ValueError(f"SHA256 mismatch: {path}")


def run(arguments, **kwargs):
    return subprocess.run([str(x) for x in arguments], check=True, **kwargs)


def git(source, *args, capture=False):
    result = run(["git", "-C", source, *args], capture_output=capture, text=True)
    return result.stdout.strip() if capture else None


def verify_sources(source, variant):
    for item in variant["source_files"]:
        verify_file(checked_child(source, item["path"]), item["sha256"], item["size"])
    changed = set(git(source, "diff", "--name-only", "HEAD", capture=True).splitlines())
    unexpected = changed - {item["path"] for item in variant["source_files"]}
    if unexpected:
        raise ValueError("Unexpected source modifications: " + ", ".join(sorted(unexpected)))


def prepare(variant_name, manifest):
    upstream = manifest["upstream"]
    variant = manifest["variants"][variant_name]
    patch = checked_child(ROOT, variant["patch"])
    verify_file(patch, variant["patch_sha256"])
    destination = RUNTIME / variant_name
    source = destination / "source"
    receipt_path = destination / "source-receipt.json"
    expected = {"commit": upstream["commit"], "patch_sha256": variant["patch_sha256"]}
    destination.mkdir(parents=True, exist_ok=True)
    if source.exists():
        if not receipt_path.exists() or read_json(receipt_path) != expected:
            raise RuntimeError(f"Existing source lacks the matching setup receipt: {source}. "
                               "Choose another checkout or move it aside before preparing again.")
        if git(source, "rev-parse", "HEAD", capture=True) != upstream["commit"]:
            raise RuntimeError(f"Source commit changed: {source}")
        verify_sources(source, variant)
        print(f"Verified prepared source: {variant_name}", flush=True)
        return source
    # A failed checkout remains visible for diagnosis; no existing files are deleted.
    run(["git", "clone", "--no-checkout", "--filter=blob:none", upstream["url"], source])
    git(source, "config", "core.autocrlf", "false")
    git(source, "-c", "core.longpaths=true", "checkout", "--detach", upstream["commit"])
    git(source, "-c", "core.whitespace=cr-at-eol", "apply", "--check", patch)
    git(source, "-c", "core.whitespace=cr-at-eol", "apply", patch)
    verify_sources(source, variant)
    write_json(receipt_path, expected)
    print(f"Prepared and verified source: {variant_name}", flush=True)
    return source


def models(args):
    specifications = read_json(ROOT / "models-manifest.json")["models"]
    explicit_paths = (args.model_path, args.drafter_path)
    locations = [(explicit or RUNTIME / "models" / spec["repo"].split("/")[-1]).resolve()
                 for spec, explicit in zip(specifications, explicit_paths, strict=True)]
    # Rechecking a previously configured directory must not leave a stale
    # verified receipt usable if its contents have changed or verification fails.
    write_json(RUNTIME / "models.json", {"models": [
        {"repo": spec["repo"], "revision": spec["revision"], "path": str(folder), "verified": False}
        for spec, folder in zip(specifications, locations, strict=True)]})
    verified = []
    for spec, explicit, folder in zip(specifications, explicit_paths, locations, strict=True):
        if not explicit:
            from huggingface_hub import snapshot_download
            print(f"Downloading pinned checkpoint {spec['repo']} ({spec['revision']})", flush=True)
            snapshot_download(repo_id=spec["repo"], revision=spec["revision"],
                              local_dir=str(folder), allow_patterns=[x["name"] for x in spec["files"]],
                              max_workers=4, token=False)
        print(f"Verifying every checkpoint file: {spec['repo']}", flush=True)
        for item in spec["files"]:
            verify_file(checked_child(folder, item["name"]), item["sha256"], item["bytes"])
        verified.append({"repo": spec["repo"], "revision": spec["revision"],
                         "path": str(folder), "verified": True})
    write_json(RUNTIME / "models.json", {"models": verified})
    print("Both checkpoints verified; wrote .runtime/models.json", flush=True)


def request(url):
    return urllib.request.urlopen(urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 TensorFold-Experiments-Setup/1"}), timeout=90)


def omp(local_path=None):
    destination = RUNTIME / "omp" / "omp.exe"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if local_path:
        verify_file(local_path, OMP_SHA256, OMP_BYTES)
        if local_path.resolve() != destination.resolve():
            shutil.copy2(local_path, destination)
    elif destination.exists():
        verify_file(destination, OMP_SHA256, OMP_BYTES)
    else:
        with request(OMP_API) as stream:
            release = json.load(stream)
        if (release["build"]["version"] != OMP_VERSION or
                release["build"]["commit"] != OMP_COMMIT or
                release["file"]["sha256"] != OMP_SHA256 or
                release["file"]["size"] != OMP_BYTES):
            raise ValueError("OMP release does not match the pinned experiment build")
        download = release["download"]
        if not download.startswith("https://"):
            raise ValueError("OMP download requires HTTPS")
        partial = destination.with_suffix(".download")
        print(f"Downloading OMP {OMP_VERSION} ({OMP_BYTES:,} bytes)", flush=True)
        with request(download) as stream, partial.open("wb") as output:
            shutil.copyfileobj(stream, output)
        verify_file(partial, OMP_SHA256, OMP_BYTES)
        partial.replace(destination)
    print(f"Verified OMP {OMP_VERSION}: {destination}", flush=True)


def msvc_environment():
    env = dict(os.environ)
    if env.get("VSCMD_ARG_TGT_ARCH", "").lower() == "x64" and shutil.which("cl.exe"):
        return env
    vswhere = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / \
        "Microsoft Visual Studio/Installer/vswhere.exe"
    if not vswhere.exists():
        raise RuntimeError("Install Visual Studio 2022 Build Tools with Desktop development with C++")
    installation = run([vswhere, "-latest", "-products", "*", "-version", "[17.0,18.0)",
                        "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
                        "-property", "installationPath"], capture_output=True, text=True).stdout.strip()
    if not installation:
        raise RuntimeError("Visual Studio 2022 C++ build tools were not found")
    vcvars = Path(installation) / "VC/Auxiliary/Build/vcvars64.bat"
    if any(x in str(vcvars) for x in '"\r\n%'):
        raise ValueError("Unsupported characters in the Visual Studio installation path")
    # cmd.exe uses its own quoting rules; list2cmdline's escaped inner quotes
    # do not work with a batch-file path containing spaces.
    command = f'cmd.exe /d /s /c ""{vcvars}" >nul && set"'
    output = subprocess.run(command, check=True, capture_output=True, text=True).stdout
    for line in output.splitlines():
        key, separator, value = line.partition("=")
        if separator and key and not key.startswith("="):
            # Environment keys are case insensitive on Windows, including PATH.
            for old_key in list(env):
                if old_key.casefold() == key.casefold():
                    env.pop(old_key)
            env[key.upper()] = value
    if not shutil.which("cl.exe", path=env.get("PATH")):
        raise RuntimeError("Visual Studio environment did not provide cl.exe")
    return env


@contextmanager
def space_free_source(source):
    """NVCC depfiles require a space-free checkout on this pinned build."""
    source = source.resolve()
    if " " not in str(source):
        yield source
        return
    buffer = ctypes.create_unicode_buffer(32768)
    ctypes.windll.kernel32.GetShortPathNameW(str(source), buffer, len(buffer))
    if buffer.value and " " not in buffer.value:
        yield Path(buffer.value)
        return
    drive = None
    for letter in "ZYXWVUTSRQPONMLKJIHGFED":
        if not ctypes.windll.kernel32.QueryDosDeviceW(letter + ":", buffer, len(buffer)):
            drive = letter + ":"
            break
    if drive is None:
        raise RuntimeError("No unused drive letter for a temporary space-free build path")
    # A module rooted at a drive root triggers Zig's Windows import boundary;
    # keep the checkout one directory below the mapped root.
    mapped = source.parent
    run(["subst.exe", drive, mapped], creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        yield Path(drive + "\\") / source.name
    finally:
        ctypes.windll.kernel32.QueryDosDeviceW(drive, buffer, len(buffer))
        if buffer.value.casefold() == ("\\??\\" + str(mapped)).casefold():
            run(["subst.exe", drive, "/d"], creationflags=subprocess.CREATE_NO_WINDOW)


def build(variant_name, manifest, args):
    if sys.platform != "win32":
        raise RuntimeError("This setup currently supports Windows x64 only")
    source = prepare(variant_name, manifest)
    zig = args.zig or shutil.which("zig.exe")
    if not zig:
        raise RuntimeError("Zig not found; pass --zig PATH/zig.exe or add it to PATH")
    zig = Path(zig).resolve()
    version = run([zig, "version"], capture_output=True, text=True).stdout.strip()
    expected = manifest["build"]
    if version != expected["zig_version"]:
        raise RuntimeError(f"Expected Zig {expected['zig_version']}, found {version}")
    cuda = args.cuda_path or (Path(os.environ["CUDA_PATH"]) if os.environ.get("CUDA_PATH") else None)
    nvcc = (cuda / "bin/nvcc.exe") if cuda else shutil.which("nvcc.exe")
    if not nvcc or not Path(nvcc).is_file():
        raise RuntimeError("NVCC not found; set CUDA_PATH or pass --cuda-path")
    nvcc = Path(nvcc).resolve()
    cuda = nvcc.parent.parent
    cuda_version = run([nvcc, "--version"], capture_output=True, text=True).stdout
    if not re.search(r"release " + re.escape(expected["cuda_version"]) + r"(?:,|\s)", cuda_version):
        raise RuntimeError(f"Expected CUDA {expected['cuda_version']}; NVCC reports:\n{cuda_version}")
    env = msvc_environment()
    env["PATH"] = str(cuda / "bin") + os.pathsep + env.get("PATH", "")
    env["NVCC_PREPEND_FLAGS"] = "--threads 2"
    destination = RUNTIME / variant_name
    with space_free_source(source) as alias:
        env["ZIG_LOCAL_CACHE_DIR"] = str(alias / ".zig-cache")
        env["ZIG_GLOBAL_CACHE_DIR"] = str(alias / ".zig-global-cache")
        command = [zig, "build", "native", "-j2", f"-Dsm={expected['sm']}",
                   "-Dstrip=true", f"-Dversion={expected['version']}", f"-Dnvcc={nvcc}"]
        log_path = destination / "build.log"
        print(f"Building {variant_name}; log: {log_path}", flush=True)
        with log_path.open("w", encoding="utf-8") as log:
            result = subprocess.run([str(x) for x in command], cwd=alias, env=env,
                                    stdout=log, stderr=subprocess.STDOUT)
        if result.returncode:
            print(log_path.read_text(encoding="utf-8", errors="replace")[-8000:], file=sys.stderr)
            raise RuntimeError(f"Build failed ({result.returncode}); inspect {log_path}")
    built = source / "zig-out/native/bin/tensorfold-native.exe"
    target = destination / "tensorfold-native.exe"
    shutil.copy2(built, target)
    write_json(destination / "build-receipt.json", {
        "variant": variant_name, "upstream": manifest["upstream"],
        "patch_sha256": manifest["variants"][variant_name]["patch_sha256"],
        "build": expected, "binary_sha256": sha256(target)})
    print(f"Built {variant_name}: {target}", flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("prepare", "build", "models", "omp", "all"), nargs="?", default="all")
    parser.add_argument("--variant", choices=(*VARIANTS, "all"), default="all")
    parser.add_argument("--zig", type=Path, help="Zig 0.17.0 executable")
    parser.add_argument("--cuda-path", type=Path, help="CUDA 13.3 toolkit directory")
    parser.add_argument("--model-path", type=Path, help="Use and verify an existing NVFP4 checkpoint")
    parser.add_argument("--drafter-path", type=Path, help="Use and verify an existing DFlash2 checkpoint")
    parser.add_argument("--omp-path", type=Path, help="Use an existing pinned OMP binary instead of downloading")
    args = parser.parse_args(argv)
    selected = VARIANTS if args.variant == "all" else (args.variant,)
    manifest = read_json(ROOT / "engine-manifest.json") if args.stage in ("prepare", "build", "all") else None
    if args.stage in ("prepare", "build", "all"):
        for name in selected:
            if args.stage == "prepare":
                prepare(name, manifest)
            else:
                build(name, manifest, args)
    if args.stage in ("models", "all"):
        models(args)
    if args.stage in ("omp", "all"):
        omp(args.omp_path)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"Setup failed: {error}", file=sys.stderr)
        raise SystemExit(1)
