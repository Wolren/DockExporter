//! .woof archive packer with seek table + xxhash integrity, plus `PyO3` bridge.

#![allow(
    clippy::useless_conversion,
    clippy::cast_possible_truncation,
    reason = "pyo3 bridges and binary format encoding use intentional usize→u32/u64 casts"
)]

use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict};

use std::collections::HashMap;

use crate::entry::{
    Entry, SeekEntry, FLAG_DEDUP, FLAG_ENTRY_ZSTD, HEADER_SIZE, WOOF_MAGIC, WOOF_VERSION,
};
use crate::error::WoofError;
use crate::seek_table;

/// Pack entries into the .woof format with dedup, seek table, and per-entry xxhash3-64 checksums.
///
/// Entries are sorted by name, optionally zstd-compressed per-entry.
/// Identical content (same xxhash3-64) is stored once and referenced by multiple
/// seek entries, enabling transparent dedup.
///
/// # Errors
/// Returns `WoofError` if zstd compression fails.
pub fn pack_archive(
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
    let mut dedup_map: HashMap<u64, (u64, u64, u32)> = HashMap::new();
    let mut dedup_occurred = false;

    for entry in sorted {
        let raw_len = entry.data.len() as u64;
        let name = entry.name;
        let hash_lo = xxhash_rust::xxh3::xxh3_64(&entry.data);

        // Check if we've already stored this content
        if let Some(&(existing_offset, existing_size, existing_flags)) = dedup_map.get(&hash_lo) {
            seek_entries.push(SeekEntry {
                flags: existing_flags,
                name,
                data_offset: existing_offset,
                data_size: existing_size,
                raw_size: raw_len,
                hash: hash_lo,
            });
            dedup_occurred = true;
            continue;
        }

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

        let data_offset = payload.len() as u64;
        let data_size = data.len() as u64;
        dedup_map.insert(hash_lo, (data_offset, data_size, flags));
        seek_entries.push(SeekEntry {
            flags,
            name,
            data_offset,
            data_size,
            raw_size: raw_len,
            hash: hash_lo,
        });
        payload.extend_from_slice(&data);
    }

    let payload_size = payload.len() as u64;
    let seek_table_bytes = seek_table::encode(&seek_entries);
    let header_flags: u64 = if dedup_occurred { FLAG_DEDUP } else { 0 };

    let mut header = Vec::with_capacity(HEADER_SIZE);
    header.extend_from_slice(WOOF_MAGIC);
    header.extend_from_slice(&WOOF_VERSION.to_le_bytes());
    header.extend_from_slice(&header_flags.to_le_bytes());
    header.extend_from_slice(&(HEADER_SIZE as u64).to_le_bytes());
    header.extend_from_slice(&(HEADER_SIZE as u64 + seek_table_bytes.len() as u64).to_le_bytes());
    header.extend_from_slice(&payload_size.to_le_bytes());
    header.extend_from_slice(&(total_raw as u64).to_le_bytes());

    let mut output = Vec::with_capacity(HEADER_SIZE + seek_table_bytes.len() + payload.len());
    output.extend_from_slice(&header);
    output.extend_from_slice(&seek_table_bytes);
    output.extend_from_slice(&payload);

    Ok(output)
}

/// `PyO3` bridge for `pack_archive`. Collects `PyBytes` references from the Python dict,
/// sorts by name, compresses, deduplicates, and produces the final archive.
#[pyfunction]
pub fn pack_woof_py<'py>(
    py: Python<'py>,
    dict: &Bound<'py, PyDict>,
    compress: bool,
    level: i32,
) -> PyResult<Py<PyBytes>> {
    let mut raw_entries: Vec<(String, Bound<'py, PyBytes>)> = Vec::with_capacity(dict.len());
    let mut total_raw: usize = 0;
    for (key, val) in dict.iter() {
        let name: String = key.extract()?;
        let pb: Bound<'py, PyBytes> = val.cast::<PyBytes>()?.clone();
        total_raw += pb.as_bytes().len();
        raw_entries.push((name, pb));
    }
    raw_entries.sort_by(|a, b| a.0.cmp(&b.0));

    let mut payload: Vec<u8> = Vec::with_capacity(total_raw);
    let mut seek_entries: Vec<SeekEntry> = Vec::with_capacity(raw_entries.len());
    let mut dedup_map: HashMap<u64, (u64, u64, u32)> = HashMap::new();
    let mut dedup_occurred = false;

    for (name, pb) in raw_entries {
        let data_ref = pb.as_bytes();
        let raw_len = data_ref.len() as u64;
        let hash_lo = xxhash_rust::xxh3::xxh3_64(data_ref);

        // Check if we've already stored this content
        if let Some(&(existing_offset, existing_size, existing_flags)) = dedup_map.get(&hash_lo) {
            seek_entries.push(SeekEntry {
                flags: existing_flags,
                name,
                data_offset: existing_offset,
                data_size: existing_size,
                raw_size: raw_len,
                hash: hash_lo,
            });
            dedup_occurred = true;
            continue;
        }

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

        let data_offset = payload.len() as u64;
        let data_size = data.len() as u64;
        dedup_map.insert(hash_lo, (data_offset, data_size, flags));
        seek_entries.push(SeekEntry {
            flags,
            name,
            data_offset,
            data_size,
            raw_size: raw_len,
            hash: hash_lo,
        });
        payload.extend_from_slice(&data);
    }

    let seek_bytes = seek_table::encode(&seek_entries);
    let payload_size = payload.len() as u64;
    let header_flags: u64 = if dedup_occurred { FLAG_DEDUP } else { 0 };

    let mut output = Vec::with_capacity(HEADER_SIZE + seek_bytes.len() + payload.len());
    output.extend_from_slice(WOOF_MAGIC);
    output.extend_from_slice(&WOOF_VERSION.to_le_bytes());
    output.extend_from_slice(&header_flags.to_le_bytes());
    output.extend_from_slice(&(HEADER_SIZE as u64).to_le_bytes());
    output.extend_from_slice(&(HEADER_SIZE as u64 + seek_bytes.len() as u64).to_le_bytes());
    output.extend_from_slice(&payload_size.to_le_bytes());
    output.extend_from_slice(&(total_raw as u64).to_le_bytes());
    output.extend_from_slice(&seek_bytes);
    output.extend_from_slice(&payload);

    Ok(PyBytes::new(py, &output).into())
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
    fn bench_pack_no_compress() {
        let entries = make_test_entries(184, 1_013_000_000);
        let start = std::time::Instant::now();
        for _ in 0..3 {
            let _ = pack_archive(entries.clone(), false, 0).unwrap();
        }
        let avg = start.elapsed() / 3;
        println!(
            "Rust pack_archive no-compress (1013 MB, 184 files, 3x): {:?} avg",
            avg
        );
    }

    #[test]
    #[ignore]
    fn bench_pack_compress() {
        let entries = make_test_entries(184, 1_013_000_000);
        let start = std::time::Instant::now();
        for _ in 0..3 {
            let _ = pack_archive(entries.clone(), true, 3).unwrap();
        }
        let avg = start.elapsed() / 3;
        println!(
            "Rust pack_archive compress (1013 MB, 184 files, 3x): {:?} avg",
            avg
        );
    }
}
