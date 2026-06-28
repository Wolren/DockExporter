"""Native Rust .woof module (optional, builds performance).

This directory is excluded from the QGIS official plugin package.
When the native module is not available, the pure-Python fallback
(dock_export/woof/woof_python.py) handles all operations transparently.

To build the native module locally:
    cd woof_native && cargo build --release
    copy target/release/_native_impl.dll ../dock_export/_woof_native/_native_impl.pyd
"""

import contextlib

with contextlib.suppress(ImportError):
    from ._native_impl import *  # noqa: F403
