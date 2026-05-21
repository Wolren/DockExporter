use pyo3::prelude::*;
use rayon::prelude::*;

use crate::entry::*;

struct CompressedEntry {
    name_bytes: Vec<u8>,
    data: Vec<u8>,
    flags: u32,
}

pub fn pack_v2(entries: Vec<(String, Vec<u8>)>, compress: bool, level: i32) -> PyResult<Vec<u8>> {
    let mut sorted: Vec<Entry> = entries
        .into_iter()
        .map(|(name, data)| Entry::new(name, data))
        .collect();
    sorted.sort();

    let total_raw: usize = sorted.par_iter().map(|e| e.data.len()).sum();

    let compressed: Vec<CompressedEntry> = sorted
        .into_par_iter()
        .map(|entry| {
            let name_bytes = entry.name.into_bytes();
            if compress {
                let cctx = zstd::bulk::Compressor::new(level as i32).unwrap();
                let compressed = cctx.compress(&entry.data).unwrap();
                if compressed.len() < entry.data.len() {
                    CompressedEntry {
                        name_bytes,
                        data: compressed,
                        flags: FLAG_ENTRY_ZSTD,
                    }
                } else {
                    CompressedEntry {
                        name_bytes,
                        data: entry.data,
                        flags: 0,
                    }
                }
            } else {
                CompressedEntry {
                    name_bytes,
                    data: entry.data,
                    flags: 0,
                }
            }
        })
        .collect();

    let mut ftable = Vec::new();
    for ce in &compressed {
        ftable.extend_from_slice(&ce.flags.to_le_bytes());
        ftable.extend_from_slice(&(ce.name_bytes.len() as u32).to_le_bytes());
        ftable.extend_from_slice(&ce.name_bytes);
        ftable.extend_from_slice(&(ce.data.len() as u64).to_le_bytes());
        ftable.extend_from_slice(&ce.data);
    }

    let payload_size = ftable.len() as u64;
    let mut header = Vec::with_capacity(HEADER_SIZE);
    header.extend_from_slice(WOOF_MAGIC);
    header.extend_from_slice(&WOOF_VERSION_V2.to_le_bytes());
    header.extend_from_slice(&0u64.to_le_bytes()); // flags
    header.extend_from_slice(&payload_size.to_le_bytes());
    header.extend_from_slice(&(total_raw as u64).to_le_bytes());

    let mut output = Vec::with_capacity(HEADER_SIZE + ftable.len());
    output.extend_from_slice(&header);
    output.extend_from_slice(&ftable);

    Ok(output)
}

#[pyfunction]
pub fn pack_v2_py(
    entries: std::collections::HashMap<String, Vec<u8>>,
    compress: bool,
    level: i32,
) -> PyResult<Vec<u8>> {
    let vec: Vec<(String, Vec<u8>)> = entries.into_iter().collect();
    pack_v2(vec, compress, level)
}
