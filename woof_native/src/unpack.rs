use pyo3::prelude::*;

use crate::entry::*;

pub fn unpack_v2(data: &[u8]) -> PyResult<Vec<(String, Vec<u8>)>> {
    if data.len() < HEADER_SIZE {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "Data too short for header",
        ));
    }

    let magic = &data[0..4];
    if magic != WOOF_MAGIC {
        return Err(pyo3::exceptions::PyValueError::new_err("Invalid magic"));
    }

    let version = u32::from_le_bytes(data[4..8].try_into().unwrap());
    if version != WOOF_VERSION_V2 {
        return Err(pyo3::exceptions::PyValueError::new_err(format!(
            "Unsupported version: {version}"
        )));
    }

    let payload_size = u64::from_le_bytes(data[16..24].try_into().unwrap()) as usize;
    if HEADER_SIZE + payload_size > data.len() {
        return Err(pyo3::exceptions::PyValueError::new_err("Truncated data"));
    }

    let payload = &data[HEADER_SIZE..HEADER_SIZE + payload_size];
    let mut entries: Vec<(String, Vec<u8>)> = Vec::new();
    let mut offset = 0usize;

    let dctx = zstd::bulk::Decompressor::new()
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;

    while offset < payload.len() {
        if offset + 8 > payload.len() {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "Truncated entry header",
            ));
        }

        let flags = u32::from_le_bytes(payload[offset..offset + 4].try_into().unwrap());
        let name_len =
            u32::from_le_bytes(payload[offset + 4..offset + 8].try_into().unwrap()) as usize;
        offset += 8;

        if offset + name_len > payload.len() {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "Truncated entry name",
            ));
        }

        let name = String::from_utf8(payload[offset..offset + name_len].to_vec())
            .map_err(|e| pyo3::exceptions::PyUnicodeDecodeError::new_err(e.to_string()))?;
        offset += name_len;

        if offset + 8 > payload.len() {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "Truncated entry data length",
            ));
        }

        let data_len = u64::from_le_bytes(payload[offset..offset + 8].try_into().unwrap()) as usize;
        offset += 8;

        if offset + data_len > payload.len() {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "Truncated entry data",
            ));
        }

        let raw = &payload[offset..offset + data_len];
        let content = if flags & FLAG_ENTRY_ZSTD != 0 {
            dctx.decompress(raw, data_len * 4)
                .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?
        } else {
            raw.to_vec()
        };
        offset += data_len;

        entries.push((name, content));
    }

    Ok(entries)
}

#[pyfunction]
pub fn unpack_v2_py(data: &[u8]) -> PyResult<std::collections::HashMap<String, Vec<u8>>> {
    let entries = unpack_v2(data)?;
    let mut map = std::collections::HashMap::new();
    for (name, content) in entries {
        map.insert(name, content);
    }
    Ok(map)
}
