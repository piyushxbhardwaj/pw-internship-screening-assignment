"""Safe ZIP handling: list image entries and extract to a work directory.

Security note: we defend against "zip-slip" (entries whose names escape the
target directory via '..' or absolute paths) and against symlink/hardlink
entries, which could otherwise write outside the extraction root.
"""

import os
import shutil
import zipfile

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp"}


def is_image(name: str) -> bool:
    return os.path.splitext(name)[1].lower() in IMAGE_EXTS


def list_image_names(zip_path: str) -> list:
    with zipfile.ZipFile(zip_path) as zf:
        return [n for n in zf.namelist() if is_image(n)]


def _safe_dest(root: str, entry_name: str) -> str:
    """Resolve a ZIP entry to a path under `root`, rejecting traversal/absolute."""
    clean = entry_name.replace("\\", "/")
    dest = os.path.realpath(os.path.join(root, clean))
    root_real = os.path.realpath(root)
    if os.path.commonpath([root_real, dest]) != root_real:
        raise ValueError(f"unsafe archive entry (path traversal): {entry_name!r}")
    return dest


def extract_images(zip_path: str, dest_dir: str) -> dict:
    """Extract image entries to dest_dir.

    Returns a dict mapping archive member name -> absolute local path.
    Non-image entries are skipped and reported separately.
    """
    extracted = {}
    skipped = []
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            name = info.filename
            if info.is_dir():
                continue
            if not is_image(name):
                skipped.append(name)
                continue
            dest = _safe_dest(dest_dir, name)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with zf.open(info) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
            extracted[name] = dest
    return {"images": extracted, "skipped": skipped}
