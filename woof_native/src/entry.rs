//! Core data types for .woof archive entries and seek-table metadata.

use std::cmp::Ordering;

/// Magic bytes identifying a .woof archive.
pub const WOOF_MAGIC: &[u8; 4] = b"WOOF";

/// Current archive format version identifier.
pub const WOOF_VERSION: u32 = 3;

/// Bit flag indicating this entry is zstd-compressed.
pub const FLAG_ENTRY_ZSTD: u32 = 2;

/// Byte size of the fixed header (48 bytes).
pub const HEADER_SIZE: usize = 48;

/// A named entry with raw (pre-compression) data.
#[derive(Clone)]
pub struct Entry {
    pub name: String,
    pub data: Vec<u8>,
}

impl Entry {
    #[must_use]
    pub const fn new(name: String, data: Vec<u8>) -> Self {
        Self { name, data }
    }
}

impl Ord for Entry {
    fn cmp(&self, other: &Self) -> Ordering {
        self.name.cmp(&other.name)
    }
}

impl PartialOrd for Entry {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}

impl Eq for Entry {}

impl PartialEq for Entry {
    fn eq(&self, other: &Self) -> bool {
        self.name == other.name
    }
}

/// Metadata entry in the seek table.
#[derive(Clone, Debug)]
pub struct SeekEntry {
    pub flags: u32,
    pub name: String,
    pub data_offset: u64,
    pub data_size: u64,
    pub raw_size: u64,
    pub hash: u64,
}
