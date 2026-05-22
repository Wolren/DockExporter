"""Unified .woof interface — prefers native Rust v3, falls back to pure Python v2."""

from .woof_python import pack_woof_to_file, extract_woof_to_directory

try:
    import native_woof_impl

    def pack_woof(
        entries: dict,
        compress: bool = True,
        level: int = 3,
    ) -> bytes:
        return native_woof_impl.pack_v3_py(entries, compress, level)

    def unpack_woof(data: bytes) -> dict:
        return native_woof_impl.unpack_v3_py(data)

    def unpack_one(data: bytes, name: str) -> bytes:
        return native_woof_impl.unpack_one_py(data, name)

    def list_entries(data: bytes) -> list:
        return native_woof_impl.list_entries_py(data)

    _HAVE_NATIVE = True

except ImportError:
    from .woof_python import pack_woof, unpack_woof

    _HAVE_NATIVE = False

    def unpack_one(data: bytes, name: str) -> bytes:
        return unpack_woof(data).get(name, b"")

    def list_entries(data: bytes) -> list:
        return []
