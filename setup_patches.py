"""自动应用 picable 兼容性补丁。

Pi 0.82.1 版本与 picable 0.1.0 存在两个兼容性问题：
1. executable 默认 "pi" 在 Windows 上无法被 subprocess 找到
2. agent_settled 事件类型未被 picable 识别

此脚本将补丁文件复制到 picable 的 site-packages 目录。

运行方式：python setup_patches.py
"""

import shutil
from pathlib import Path

PATCHES_DIR = Path(__file__).resolve().parent / "patches"


def _find_picable_dir() -> Path:
    import picable
    return Path(picable.__file__).parent


def apply() -> None:
    picable_dir = _find_picable_dir()
    print(f"picable location: {picable_dir}")

    targets = {
        "events.py": picable_dir / "events.py",
    }

    for src_name, dst in targets.items():
        src = PATCHES_DIR / src_name
        if not src.exists():
            print(f"  SKIP {src_name}: not found in patches/")
            continue
        shutil.copy2(str(src), str(dst))
        print(f"  PATCHED {src_name} -> {dst}")

    print("Patches applied successfully.")


if __name__ == "__main__":
    apply()
