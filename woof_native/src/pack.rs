//! .woof archive packer. Provides v2 (legacy flat table) and v3 (seek table + xxhash integrity)
//! encoders, plus `PyO3` bridge functions for Python callers.

#![allow(
    clippy::useless_conversion,
    clippy::cast_possible_truncation,
    reason = "pyo3 bridges and binary format encoding use intentional usize→u32/u64 casts"
)]

use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict};

use crate::entry::{
    Entry, SeekEntry, FLAG_ENTRY_ZSTD, V2_HEADER_SIZE, V3_HEADER_SIZE, WOOF_MAGIC, WOOF_VERSION_V2,
    WOOF_VERSION_V3,
};
use crate::error::WoofError;
use crate::seek_table;

/// Pack entries into the legacy v2 format. Sorts entries by name, optionally zstd-compresses,
/// and produces a flat table with inline flags/name/length/data fields.
///
/// # Errors
/// Returns `PyErr` if zstd compression fails.
pub fn pack_v2(entries: Vec<(String, Vec<u8>)>, compress: bool, level: i32) -> PyResult<Vec<u8>> {
    let mut sorted: Vec<Entry> = entries
        .into_iter()
        .map(|(name, data)| Entry::new(name, data))
        .collect();
    sorted.sort();

    let total_raw: usize = sorted.iter().map(|e| e.data.len()).sum();

    let mut ftable = Vec::new();
    for entry in &sorted {
        let (data, flags) = if compress {
            let mut cctx = zstd::bulk::Compressor::new(level)
                .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;
            let compressed = cctx
                .compress(&entry.data)
                .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;
            if compressed.len() < entry.data.len() {
                (compressed, FLAG_ENTRY_ZSTD)
            } else {
                (entry.data.clone(), 0)
            }
        } else {
            (entry.data.clone(), 0)
        };
        ftable.extend_from_slice(&flags.to_le_bytes());
        ftable.extend_from_slice(&(entry.name.len() as u32).to_le_bytes());
        ftable.extend_from_slice(entry.name.as_bytes());
        ftable.extend_from_slice(&(data.len() as u64).to_le_bytes());
        ftable.extend_from_slice(&data);
    }

    let payload_size = ftable.len() as u64;
    let mut header = Vec::with_capacity(V2_HEADER_SIZE);
    header.extend_from_slice(WOOF_MAGIC);
    header.extend_from_slice(&WOOF_VERSION_V2.to_le_bytes());
    header.extend_from_slice(&0u64.to_le_bytes());
    header.extend_from_slice(&payload_size.to_le_bytes());
    header.extend_from_slice(&(total_raw as u64).to_le_bytes());

    let mut output = Vec::with_capacity(V2_HEADER_SIZE + ftable.len());
    output.extend_from_slice(&header);
    output.extend_from_slice(&ftable);

    Ok(output)
}

/// `PyO3` bridge for `pack_v2`. Accepts a Python dict mapping names to bytes.
#[pyfunction]
pub fn pack_v2_py<'py>(
    py: Python<'py>,
    dict: &Bound<'py, PyDict>,
    compress: bool,
    level: i32,
) -> PyResult<Py<PyBytes>> {
    let mut entries: Vec<(String, Vec<u8>)> = Vec::with_capacity(dict.len());
    for (key, val) in dict.iter() {
        entries.push((key.extract()?, val.extract()?));
    }
    let output = pack_v2(entries, compress, level)?;
    Ok(PyBytes::new_bound(py, &output).into())
}

/// Pack entries into the v3 format with a seek table and per-entry xxhash3-64 checksums.
///
/// Entries are sorted by name, optionally zstd-compressed per-entry,
/// and the seek table enables O(log n) lookup and random access.
///
/// # Errors
/// Returns `WoofError` if zstd compression fails.
pub fn pack_v3(
    entries: Vec<(String, Vec<u8>)>,
    compress: bool,
    level: i32,
) -> Result<Vec<u8>, WoofError> {
    let mut sorted: Vec<Entry> = entries
        .into_iter()
        .map(|(name, data)| Entry::new(name, data))
        .collect();
    sorted.sort();

    let total_raw: usize = sorted.iter().map(|e| e.data.len()).sum();

    let mut payload = Vec::with_capacity(total_raw);
    let mut seek_entries: Vec<SeekEntry> = Vec::with_capacity(sorted.len());
    for entry in sorted {
        let raw_len = entry.data.len() as u64;
        let name = entry.name;
        let hash_lo = xxhash_rust::xxh3::xxh3_64(&entry.data);
        let (data, flags) = if compress {
            match zstd::bulk::compress(&entry.data, level) {
                Ok(compressed) if compressed.len() < entry.data.len() => {
                    (compressed, FLAG_ENTRY_ZSTD)
                }
                _ => (entry.data, 0),
            }
        } else {
            (entry.data, 0)
        };

        seek_entries.push(SeekEntry {
            flags,
            name,
            data_offset: payload.len() as u64,
            data_size: data.len() as u64,
            raw_size: raw_len,
            hash: hash_lo,
        });
        payload.extend_from_slice(&data);
    }

    let payload_size = payload.len() as u64;
    let seek_table_bytes = seek_table::encode(&seek_entries);

    let mut header = Vec::with_capacity(V3_HEADER_SIZE);
    header.extend_from_slice(WOOF_MAGIC);
    header.extend_from_slice(&WOOF_VERSION_V3.to_le_bytes());
    header.extend_from_slice(&0u64.to_le_bytes());
    header.extend_from_slice(&(V3_HEADER_SIZE as u64).to_le_bytes());
    header
        .extend_from_slice(&(V3_HEADER_SIZE as u64 + seek_table_bytes.len() as u64).to_le_bytes());
    header.extend_from_slice(&payload_size.to_le_bytes());
    header.extend_from_slice(&(total_raw as u64).to_le_bytes());

    let mut output = Vec::with_capacity(V3_HEADER_SIZE + seek_table_bytes.len() + payload.len());
    output.extend_from_slice(&header);
    output.extend_from_slice(&seek_table_bytes);
    output.extend_from_slice(&payload);

    Ok(output)
}

/// `PyO3` bridge for `pack_v3`. Collects `PyBytes` references from the Python dict,
/// sorts by name, compresses, and produces the final archive.
#[pyfunction]
pub fn pack_v3_py<'py>(
    py: Python<'py>,
    dict: &Bound<'py, PyDict>,
    compress: bool,
    level: i32,
) -> PyResult<Py<PyBytes>> {
    let mut raw_entries: Vec<(String, Bound<'py, PyBytes>)> = Vec::with_capacity(dict.len());
    let mut total_raw: usize = 0;
    for (key, val) in dict.iter() {
        let name: String = key.extract()?;
        let pb: Bound<'py, PyBytes> = val.downcast::<PyBytes>()?.clone();
        total_raw += pb.as_bytes().len();
        raw_entries.push((name, pb));
    }
    raw_entries.sort_by(|a, b| a.0.cmp(&b.0));

    let mut payload: Vec<u8> = Vec::with_capacity(total_raw);
    let mut seek_entries: Vec<SeekEntry> = Vec::with_capacity(raw_entries.len());
    for (name, pb) in raw_entries {
        let data_ref = pb.as_bytes();
        let raw_len = data_ref.len() as u64;
        let hash_lo = xxhash_rust::xxh3::xxh3_64(data_ref);

        let (data, flags) = if compress {
            match zstd::bulk::compress(data_ref, level) {
                Ok(compressed) if compressed.len() < data_ref.len() => {
                    (compressed, FLAG_ENTRY_ZSTD)
                }
                _ => (data_ref.to_vec(), 0),
            }
        } else {
            (data_ref.to_vec(), 0)
        };

        seek_entries.push(SeekEntry {
            flags,
            name,
            data_offset: payload.len() as u64,
            data_size: data.len() as u64,
            raw_size: raw_len,
            hash: hash_lo,
        });
        payload.extend_from_slice(&data);
    }

    let seek_bytes = seek_table::encode(&seek_entries);
    let payload_size = payload.len() as u64;

    let mut output = Vec::with_capacity(V3_HEADER_SIZE + seek_bytes.len() + payload.len());
    output.extend_from_slice(WOOF_MAGIC);
    output.extend_from_slice(&WOOF_VERSION_V3.to_le_bytes());
    output.extend_from_slice(&0u64.to_le_bytes());
    output.extend_from_slice(&(V3_HEADER_SIZE as u64).to_le_bytes());
    output.extend_from_slice(&(V3_HEADER_SIZE as u64 + seek_bytes.len() as u64).to_le_bytes());
    output.extend_from_slice(&payload_size.to_le_bytes());
    output.extend_from_slice(&(total_raw as u64).to_le_bytes());
    output.extend_from_slice(&seek_bytes);
    output.extend_from_slice(&payload);

    Ok(PyBytes::new_bound(py, &output).into())
}

#[cfg(test)]
mod benchmarks {
    use super::*;

    fn make_test_entries(count: usize, total_size: usize) -> Vec<(String, Vec<u8>)> {
        let per_entry = total_size / count;
        (0..count)
            .map(|i| {
                let name = format!("file_{:04}.tif", i);
                let size = if i == count - 1 {
                    total_size - (per_entry * (count - 1))
                } else {
                    per_entry
                };
                let data = vec![0xABu8; size];
                (name, data)
            })
            .collect()
    }

    #[test]
    fn test_zstd_bulk_compress() {
        let data = vec![0xABu8; 500000];
        let compressed = zstd::bulk::compress(&data, 3).unwrap();
        assert!(
            compressed.len() < data.len(),
            "zstd bulk compress should reduce 500K zeros: {} vs {}",
            compressed.len(),
            data.len()
        );
    }

    #[test]
    fn test_zstd_encode_all() {
        let data = vec![0xABu8; 500000];
        let compressed = zstd::encode_all(std::io::Cursor::new(&data), 3).unwrap();
        assert!(
            compressed.len() < data.len(),
            "zstd encode_all should reduce 500K zeros: {} vs {}",
            compressed.len(),
            data.len()
        );
    }

    #[test]
    #[ignore]
    fn bench_pack_v3_no_compress() {
        let entries = make_test_entries(184, 1_013_000_000);
        let start = std::time::Instant::now();
        for _ in 0..3 {
            let _ = pack_v3(entries.clone(), false, 0).unwrap();
        }
        let avg = start.elapsed() / 3;
        println!(
            "Rust pack_v3 no-compress (1013 MB, 184 files, 3x): {:?} avg",
            avg
        );
    }

    #[test]
    #[ignore]
    fn bench_pack_v3_compress() {
        let entries = make_test_entries(184, 1_013_000_000);
        let start = std::time::Instant::now();
        for _ in 0..3 {
            let _ = pack_v3(entries.clone(), true, 3).unwrap();
        }
        let avg = start.elapsed() / 3;
        println!(
            "Rust pack_v3 compress (1013 MB, 184 files, 3x): {:?} avg",
            avg
        );
    }
}
