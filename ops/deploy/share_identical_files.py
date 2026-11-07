"""Make identical files at the same path in two folders share one copy, using hard links.

The image and voice runtimes pin the same PyTorch, so about 7 GB of the second is a copy of the
first. Nothing writes to these folders at runtime. Standard library only.

    python share_identical_files.py <first folder> <second folder>
"""

import filecmp
import os
import sys
from pathlib import Path


def share(first: Path, second: Path) -> int:
    """Link each file in ``second`` to its identical twin in ``first``. Returns the bytes saved."""
    saved = 0
    for path in second.rglob("*"):
        other = first / path.relative_to(second)
        if path.is_symlink() or other.is_symlink() or not path.is_file() or not other.is_file():
            continue
        if filecmp.cmp(path, other, shallow=False):
            saved += path.stat().st_size
            path.unlink()
            os.link(other, path)
    return saved


if __name__ == "__main__":
    print(f"shared {share(Path(sys.argv[1]), Path(sys.argv[2])) / 1e9:.2f} GB")
