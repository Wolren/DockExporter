//! Seek-table encode/decode for the v3 .woof format. Maps entry names to their offset, size,
//! compression flags, and xxhash3-64 checksum within the payload section.

use crate::entry::SeekEntry;
use crate::error::WoofError;

/// Byte size of a single seek-table entry in the binary encoding (44 bytes).
pub const SEEK_ENTRY_SIZE: usize = 44;

/// Encode seek table entries into bytes:
/// `[num_entries:u32] [entries × SEEK_ENTRY_SIZE bytes] [name heap]`
#[must_use]
#[allow(clippy::cast_possible_truncation)]
pub fn encode(entries: &[SeekEntry]) -> Vec<u8> {
    let name_heap_size: usize = entries.iter().map(|e| e.name.len()).sum();
    let total_size = 4 + entries.len() * SEEK_ENTRY_SIZE + name_heap_size;
    let mut buf = Vec::with_capacity(total_size);
    buf.extend_from_slice(&(entries.len() as u32).to_le_bytes());

    let mut name_offset: u32 = 0;
    for e in entries {
        buf.extend_from_slice(&e.flags.to_le_bytes());
        buf.extend_from_slice(&(e.name.len() as u32).to_le_bytes());
        buf.extend_from_slice(&name_offset.to_le_bytes());
        buf.extend_from_slice(&e.data_offset.to_le_bytes());
        buf.extend_from_slice(&e.data_size.to_le_bytes());
        buf.extend_from_slice(&e.raw_size.to_le_bytes());
        buf.extend_from_slice(&e.hash.to_le_bytes());
        name_offset += e.name.len() as u32;
    }

    for e in entries {
        buf.extend_from_slice(e.name.as_bytes());
    }

    buf
}

/// Decode seek table from bytes at the given offset.
/// Returns `(entries, new_offset)` where `new_offset` is past the entire seek table.
#[allow(clippy::cast_possible_truncation)]
pub fn decode(data: &[u8], offset: usize) -> Result<(Vec<SeekEntry>, usize), WoofError> {
    if offset + 4 > data.len() {
        return Err(WoofError::Truncated(offset));
    }

    let num_entries = u32::from_le_bytes(
        data[offset..offset + 4]
            .try_into()
            .expect("offset bounds checked above"),
    ) as usize;
    let entry_table_size = num_entries * SEEK_ENTRY_SIZE;

    if offset + 4 + entry_table_size > data.len() {
        return Err(WoofError::Truncated(offset + 4 + entry_table_size));
    }

    let table_start = offset + 4;
    let heap_start = table_start + entry_table_size;

    let mut entries = Vec::with_capacity(num_entries);
    let mut name_heap_offset: u32 = 0;

    for i in 0..num_entries {
        let pos = table_start + i * SEEK_ENTRY_SIZE;
        let flags = u32::from_le_bytes(
            data[pos..pos + 4]
                .try_into()
                .expect("entry table bounds checked above"),
        );
        let name_len = u32::from_le_bytes(
            data[pos + 4..pos + 8]
                .try_into()
                .expect("entry table bounds checked above"),
        ) as usize;
        let _name_offset = u32::from_le_bytes(
            data[pos + 8..pos + 12]
                .try_into()
                .expect("entry table bounds checked above"),
        );
        let data_offset = u64::from_le_bytes(
            data[pos + 12..pos + 20]
                .try_into()
                .expect("entry table bounds checked above"),
        );
        let data_size = u64::from_le_bytes(
            data[pos + 20..pos + 28]
                .try_into()
                .expect("entry table bounds checked above"),
        );
        let raw_size = u64::from_le_bytes(
            data[pos + 28..pos + 36]
                .try_into()
                .expect("entry table bounds checked above"),
        );
        let hash = u64::from_le_bytes(
            data[pos + 36..pos + 44]
                .try_into()
                .expect("entry table bounds checked above"),
        );

        let name_start = heap_start + name_heap_offset as usize;
        let name_end = name_start + name_len;
        if name_end > data.len() {
            return Err(WoofError::Truncated(name_end));
        }
        let name = String::from_utf8(data[name_start..name_end].to_vec())?;
        name_heap_offset += name_len as u32;

        entries.push(SeekEntry {
            flags,
            name,
            data_offset,
            data_size,
            raw_size,
            hash,
        });
    }

    let total_bytes = 4 + entry_table_size + name_heap_offset as usize;
    Ok((entries, offset + total_bytes))
}

/// Find entry by name via binary search. Returns index or `None`.
#[must_use]
pub fn find_entry(entries: &[SeekEntry], name: &str) -> Option<usize> {
    entries.binary_search_by(|e| e.name.as_str().cmp(name)).ok()
}
