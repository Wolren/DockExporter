"""Unified .woof interface — prefers native Rust v3, falls back to pure Python v2."""

import os

from .woof_python import pack_woof_to_file

try:
    import native_woof_impl

    def pack_woof(
        entries: dict,
        compress: bool = True,
        level: int = 3,
    ) -> bytes:
        """Pack *entries* into a v3 .woof archive in memory."""
        return native_woof_impl.pack_v3_py(entries, compress, level)

    def unpack_woof(data: bytes) -> dict:
        """Unpack a v3 .woof archive from *data* into a dict of {name: bytes}."""
        return native_woof_impl.unpack_v3_py(data)

    def unpack_one(data: bytes, name: str) -> bytes:
        """Extract a single entry *name* from a v3 .woof archive without full decompress."""
        return native_woof_impl.unpack_one_py(data, name)

    def list_entries(data: bytes) -> list:
        """Return the list of entry names in a v3 .woof archive."""
        return native_woof_impl.list_entries_py(data)

    _HAVE_NATIVE = True

except ImportError:
    from .woof_python import pack_woof, unpack_woof

    _HAVE_NATIVE = False

    def unpack_one(data: bytes, name: str) -> bytes:
        """Fallback: unpack full archive and retrieve *name*."""
        return unpack_woof(data).get(name, b"")

    def list_entries(_data: bytes) -> list:
        """Fallback: return empty list (v2 format has no index)."""
        return []


def extract_woof_to_directory(data: bytes, target_dir: str) -> None:
    """Extract a .woof archive into *target_dir*, recreating directory structure."""
    entries = unpack_woof(data)
    os.makedirs(target_dir, exist_ok=True)
    for arcname, content in entries.items():
        dst = os.path.join(target_dir, arcname)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "wb") as f:
            f.write(content)
