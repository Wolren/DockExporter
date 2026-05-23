//! Error types for .woof archive operations.

use thiserror::Error;

/// Errors that can occur during .woof pack, unpack, or integrity verification.
#[derive(Error, Debug)]
pub enum WoofError {
    #[error("I/O error: {0}")]
    Io(#[from] std::io::Error),

    #[error("Invalid magic bytes")]
    BadMagic,

    #[error("Unsupported version: {0}")]
    BadVersion(u32),

    #[error("Truncated data at offset {0}")]
    Truncated(usize),

    #[error("Checksum mismatch for entry '{0}'")]
    ChecksumMismatch(String),

    #[error("Compression error: {0}")]
    Compress(String),

    #[error("Decompression error: {0}")]
    Decompress(String),

    #[error("Entry '{0}' not found")]
    EntryNotFound(String),

    #[error("UTF-8 error: {0}")]
    BadName(#[from] std::string::FromUtf8Error),
}

#[allow(clippy::match_same_arms)]
impl From<WoofError> for pyo3::PyErr {
    fn from(e: WoofError) -> Self {
        let msg = e.to_string();
        match &e {
            WoofError::BadMagic | WoofError::BadVersion(_) | WoofError::Truncated(_) => {
                pyo3::exceptions::PyValueError::new_err(msg)
            }
            WoofError::ChecksumMismatch(_) => pyo3::exceptions::PyRuntimeError::new_err(msg),
            WoofError::EntryNotFound(_) => pyo3::exceptions::PyKeyError::new_err(msg),
            _ => pyo3::exceptions::PyRuntimeError::new_err(msg),
        }
    }
}
