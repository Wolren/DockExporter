"""Unified .woof interface backed by the native Rust module."""

import os

try:
    import native_woof_impl

    def pack_woof(
        entries: dict,
        compress: bool = True,
        level: int = 3,
    ) -> bytes:
        """Pack *entries* into a .woof archive in memory."""
        return native_woof_impl.pack_woof_py(entries, compress, level)

    def unpack_woof(data: bytes) -> dict:
        """Unpack a .woof archive from *data* into a dict of {name: bytes}."""
        return native_woof_impl.unpack_woof_py(data)

    def unpack_one(data: bytes, name: str) -> bytes:
        """Extract a single entry *name* from a .woof archive without full decompress."""
        return native_woof_impl.unpack_one_py(data, name)

    def list_entries(data: bytes) -> list:
        """Return the list of entry names in a .woof archive."""
        return native_woof_impl.list_entries_py(data)

    def pack_woof_to_file(
        output_path: str,
        entries,
        compress: bool = True,
        level: int = 3,
        progress_cb=None,
    ) -> None:
        """Pack entries into a .woof archive written directly to *output_path*."""
        entry_dict = dict(entries)
        if progress_cb:
            total = len(entry_dict)
            for idx, name in enumerate(entry_dict):
                progress_cb(idx, total)
        data = native_woof_impl.pack_woof_py(entry_dict, compress, level)
        with open(output_path, "wb") as f:
            f.write(data)

    _HAVE_NATIVE = True

except ImportError:
    _HAVE_NATIVE = False

    def pack_woof(entries: dict, compress: bool = True, level: int = 3) -> bytes:
        raise RuntimeError("Native .woof module not available")

    def unpack_woof(data: bytes) -> dict:
        raise RuntimeError("Native .woof module not available")

    def unpack_one(data: bytes, name: str) -> bytes:
        raise RuntimeError("Native .woof module not available")

    def list_entries(data: bytes) -> list:
        raise RuntimeError("Native .woof module not available")

    def pack_woof_to_file(
        output_path, entries, compress=True, level=3, progress_cb=None
    ):
        raise RuntimeError("Native .woof module not available")


def extract_woof_to_directory(data: bytes, target_dir: str) -> None:
    """Extract a .woof archive into *target_dir*, recreating directory structure."""
    entries = unpack_woof(data)
    os.makedirs(target_dir, exist_ok=True)
    for arcname, content in entries.items():
        dst = os.path.join(target_dir, arcname)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "wb") as f:
            f.write(content)
