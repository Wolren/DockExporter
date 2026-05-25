//! .woof archive unpacker with seek table + xxhash integrity verification, plus `PyO3` bridge.

#![allow(
    clippy::useless_conversion,
    clippy::cast_possible_truncation,
    reason = "pyo3 bridges and binary format parsing use intentional casts"
)]

use pyo3::prelude::*;
use pyo3::types::PyBytes;
use std::collections::HashMap;

use crate::entry::{SeekEntry, FLAG_ENTRY_ZSTD, HEADER_SIZE, WOOF_MAGIC, WOOF_VERSION};
use crate::error::WoofError;
use crate::seek_table;

/// Parse the header and seek table, returning `(seek_entries, payload_slice, total_raw)`.
fn parse_archive(data: &[u8]) -> Result<(Vec<SeekEntry>, &[u8], u64), WoofError> {
    if data.len() < HEADER_SIZE {
        return Err(WoofError::Truncated(data.len()));
    }

    if &data[0..4] != WOOF_MAGIC {
        return Err(WoofError::BadMagic);
    }

    let version = u32::from_le_bytes(
        data[4..8]
            .try_into()
            .expect("data.len() >= HEADER_SIZE checked above"),
    );
    if version != WOOF_VERSION {
        return Err(WoofError::BadVersion(version));
    }

    let seek_offset = u64::from_le_bytes(
        data[16..24]
            .try_into()
            .expect("HEADER_SIZE >= 48 checked above"),
    ) as usize;
    let payload_offset = u64::from_le_bytes(
        data[24..32]
            .try_into()
            .expect("HEADER_SIZE >= 48 checked above"),
    ) as usize;
    let payload_size = u64::from_le_bytes(
        data[32..40]
            .try_into()
            .expect("HEADER_SIZE >= 48 checked above"),
    ) as usize;
    let total_raw = u64::from_le_bytes(
        data[40..48]
            .try_into()
            .expect("HEADER_SIZE >= 48 checked above"),
    );

    if seek_offset > data.len() || payload_offset > data.len() {
        return Err(WoofError::Truncated(data.len()));
    }
    if payload_offset + payload_size > data.len() {
        return Err(WoofError::Truncated(payload_offset + payload_size));
    }

    let (seek_entries, _) = seek_table::decode(data, seek_offset)?;
    let payload = &data[payload_offset..payload_offset + payload_size];

    Ok((seek_entries, payload, total_raw))
}

/// Unpack all entries from an archive. Verifies per-entry xxhash3-64 checksums.
pub fn unpack_archive(data: &[u8]) -> Result<Vec<(String, Vec<u8>)>, WoofError> {
    let (seek_entries, payload, _) = parse_archive(data)?;

    let mut results = Vec::with_capacity(seek_entries.len());
    for entry in &seek_entries {
        let start = entry.data_offset as usize;
        let end = start + entry.data_size as usize;
        if end > payload.len() {
            return Err(WoofError::Truncated(end));
        }

        let raw = &payload[start..end];
        let decompressed = if entry.flags & FLAG_ENTRY_ZSTD != 0 {
            let mut dctx = zstd::bulk::Decompressor::new()
                .map_err(|e| WoofError::Decompress(e.to_string()))?;
            dctx.decompress(raw, entry.raw_size as usize)
                .map_err(|e| WoofError::Decompress(e.to_string()))?
        } else {
            raw.to_vec()
        };

        let computed = xxhash_rust::xxh3::xxh3_64(&decompressed);
        if computed != entry.hash {
            return Err(WoofError::ChecksumMismatch(entry.name.clone()));
        }

        results.push((entry.name.clone(), decompressed));
    }

    Ok(results)
}

/// Unpack a single entry by name. O(log n) via binary search on the seek table.
///
/// # Errors
/// Returns `WoofError` if the entry is not found, decompression fails, or checksum mismatch.
pub fn unpack_one(data: &[u8], name: &str) -> Result<Vec<u8>, WoofError> {
    let (seek_entries, payload, _) = parse_archive(data)?;

    let idx = seek_table::find_entry(&seek_entries, name)
        .ok_or_else(|| WoofError::EntryNotFound(name.to_string()))?;

    let entry = &seek_entries[idx];
    let start = entry.data_offset as usize;
    let end = start + entry.data_size as usize;
    if end > payload.len() {
        return Err(WoofError::Truncated(end));
    }

    let raw = &payload[start..end];
    let decompressed = if entry.flags & FLAG_ENTRY_ZSTD != 0 {
        let mut dctx =
            zstd::bulk::Decompressor::new().map_err(|e| WoofError::Decompress(e.to_string()))?;
        dctx.decompress(raw, entry.raw_size as usize)
            .or_else(|_| zstd::decode_all(raw).map_err(|e| WoofError::Decompress(e.to_string())))?
    } else {
        raw.to_vec()
    };

    let computed = xxhash_rust::xxh3::xxh3_64(&decompressed);
    if computed != entry.hash {
        return Err(WoofError::ChecksumMismatch(entry.name.clone()));
    }

    Ok(decompressed)
}

/// List all seek entries without decompressing payloads.
pub fn list_entry_infos(data: &[u8]) -> Result<Vec<SeekEntry>, WoofError> {
    let (seek_entries, _, _) = parse_archive(data)?;
    Ok(seek_entries)
}

/// `PyO3` bridge for unpacking all entries. Returns a Python dict.
#[pyfunction]
pub fn unpack_woof_py(py: Python<'_>, data: &[u8]) -> PyResult<HashMap<String, Py<PyBytes>>> {
    let (seek_entries, payload, _) = parse_archive(data)?;

    let mut map = HashMap::with_capacity(seek_entries.len());
    for entry in &seek_entries {
        let start = entry.data_offset as usize;
        let end = start + entry.data_size as usize;
        if end > payload.len() {
            return Err(WoofError::Truncated(end).into());
        }

        let raw = &payload[start..end];

        if entry.flags & FLAG_ENTRY_ZSTD != 0 {
            let mut dctx = zstd::bulk::Decompressor::new()
                .map_err(|e| WoofError::Decompress(e.to_string()))?;
            let decompressed = dctx
                .decompress(raw, entry.raw_size as usize)
                .map_err(|e| WoofError::Decompress(e.to_string()))?;
            let computed = xxhash_rust::xxh3::xxh3_64(&decompressed);
            if computed != entry.hash {
                return Err(WoofError::ChecksumMismatch(entry.name.clone()).into());
            }
            map.insert(
                entry.name.clone(),
                PyBytes::new_bound(py, &decompressed).into(),
            );
        } else {
            let computed = xxhash_rust::xxh3::xxh3_64(raw);
            if computed != entry.hash {
                return Err(WoofError::ChecksumMismatch(entry.name.clone()).into());
            }
            map.insert(entry.name.clone(), PyBytes::new_bound(py, raw).into());
        }
    }

    Ok(map)
}

/// `PyO3` bridge for single-entry lookup. Returns the decompressed bytes for one entry.
#[pyfunction]
pub fn unpack_one_py(py: Python<'_>, data: &[u8], name: &str) -> PyResult<Py<PyBytes>> {
    let (seek_entries, payload, _) = parse_archive(data)?;
    let idx = seek_table::find_entry(&seek_entries, name)
        .ok_or_else(|| WoofError::EntryNotFound(name.to_string()))?;
    let entry = &seek_entries[idx];

    let start = entry.data_offset as usize;
    let end = start + entry.data_size as usize;
    if end > payload.len() {
        return Err(WoofError::Truncated(end).into());
    }
    let raw = &payload[start..end];

    if entry.flags & FLAG_ENTRY_ZSTD != 0 {
        let mut dctx =
            zstd::bulk::Decompressor::new().map_err(|e| WoofError::Decompress(e.to_string()))?;
        let decompressed = dctx
            .decompress(raw, entry.raw_size as usize)
            .map_err(|e| WoofError::Decompress(e.to_string()))?;
        let computed = xxhash_rust::xxh3::xxh3_64(&decompressed);
        if computed != entry.hash {
            return Err(WoofError::ChecksumMismatch(entry.name.clone()).into());
        }
        Ok(PyBytes::new_bound(py, &decompressed).into())
    } else {
        let computed = xxhash_rust::xxh3::xxh3_64(raw);
        if computed != entry.hash {
            return Err(WoofError::ChecksumMismatch(entry.name.clone()).into());
        }
        Ok(PyBytes::new_bound(py, raw).into())
    }
}

/// `PyO3` bridge for listing entry metadata without decompression.
/// Returns a list of `(name, flags, data_size, raw_size, hash)` tuples.
#[pyfunction]
#[allow(clippy::type_complexity)]
pub fn list_entries_py(data: &[u8]) -> PyResult<Vec<(String, u32, u64, u64, u64)>> {
    let entries = list_entry_infos(data)?;
    Ok(entries
        .into_iter()
        .map(|e| (e.name, e.flags, e.data_size, e.raw_size, e.hash))
        .collect())
}
