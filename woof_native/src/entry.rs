use std::cmp::Ordering;

pub const WOOF_MAGIC: &[u8; 4] = b"WOOF";
pub const WOOF_VERSION_V2: u32 = 2;
pub const FLAG_ENTRY_ZSTD: u32 = 2;
pub const HEADER_SIZE: usize = 32;

#[derive(Clone)]
pub struct Entry {
    pub name: String,
    pub data: Vec<u8>,
}

impl Entry {
    pub fn new(name: String, data: Vec<u8>) -> Self {
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
