/// Integration tests for .woof format roundtrips, integrity checks, and error handling.
use std::collections::HashMap;

/// Roundtrip without compression preserves data.
#[test]
fn test_roundtrip_no_compress() {
    let entries = vec![
        ("a.txt".into(), b"hello".to_vec()),
        ("b.txt".into(), b"world".to_vec()),
    ];

    let result = _native_impl::pack::pack_archive(entries, false, 3).unwrap();
    let unpacked = _native_impl::unpack::unpack_archive(&result).unwrap();

    let map: HashMap<String, Vec<u8>> = unpacked.into_iter().collect();
    assert_eq!(map.get("a.txt").map(|v| v.as_slice()), Some(&b"hello"[..]));
    assert_eq!(map.get("b.txt").map(|v| v.as_slice()), Some(&b"world"[..]));
}

/// Roundtrip with compression preserves data.
#[test]
fn test_roundtrip_compress() {
    let data = "A".repeat(1000);
    let entries = vec![("compressible.txt".into(), data.as_bytes().to_vec())];

    let result = _native_impl::pack::pack_archive(entries, true, 3).unwrap();
    let unpacked = _native_impl::unpack::unpack_archive(&result).unwrap();

    assert_eq!(unpacked[0].1, data.as_bytes());
}

/// Output is deterministic regardless of input order.
#[test]
fn test_deterministic() {
    let entries1 = vec![
        ("z.txt".into(), b"last".to_vec()),
        ("a.txt".into(), b"first".to_vec()),
    ];
    let entries2 = vec![
        ("a.txt".into(), b"first".to_vec()),
        ("z.txt".into(), b"last".to_vec()),
    ];

    let r1 = _native_impl::pack::pack_archive(entries1, false, 3).unwrap();
    let r2 = _native_impl::pack::pack_archive(entries2, false, 3).unwrap();
    assert_eq!(
        r1, r2,
        "output should be deterministic regardless of input order"
    );
}

/// Rejects invalid magic bytes.
#[test]
fn test_invalid_magic() {
    let data = b"NOTWOOF".to_vec();
    let result = _native_impl::unpack::unpack_archive(&data);
    assert!(result.is_err());
}

/// Roundtrip with compression preserves highly compressible data.
#[test]
fn test_always_compress() {
    let entries = vec![("raster.tif".into(), vec![0u8; 500])];
    let result = _native_impl::pack::pack_archive(entries.clone(), true, 3).unwrap();
    let unpacked = _native_impl::unpack::unpack_archive(&result).unwrap();
    assert_eq!(
        unpacked[0].1,
        vec![0u8; 500],
        "roundtrip should preserve data"
    );
}

/// Tampering with the payload after packing is detected by per-entry xxhash checksums.
#[test]
fn test_integrity_check() {
    let entries = vec![("a.txt".into(), b"hello".to_vec())];

    let mut result = _native_impl::pack::pack_archive(entries, false, 3).unwrap();
    let payload_offset = u64::from_le_bytes(result[24..32].try_into().unwrap()) as usize;
    result[payload_offset] ^= 0xFF;

    let unpack_result = _native_impl::unpack::unpack_archive(&result);
    assert!(unpack_result.is_err(), "should detect tampered data");
    assert!(
        unpack_result
            .unwrap_err()
            .to_string()
            .contains("Checksum mismatch"),
        "error should mention checksum"
    );
}

/// Single-entry extraction by name works correctly.
#[test]
fn test_unpack_one() {
    let entries = vec![
        ("z.txt".into(), b"last".to_vec()),
        ("a.txt".into(), b"first".to_vec()),
    ];

    let result = _native_impl::pack::pack_archive(entries, false, 3).unwrap();

    let a = _native_impl::unpack::unpack_one(&result, "a.txt").unwrap();
    assert_eq!(a, b"first");

    let z = _native_impl::unpack::unpack_one(&result, "z.txt").unwrap();
    assert_eq!(z, b"last");
}

/// Requesting a non-existent entry returns an error.
#[test]
fn test_unpack_one_not_found() {
    let entries = vec![("a.txt".into(), b"data".to_vec())];
    let result = _native_impl::pack::pack_archive(entries, false, 3).unwrap();

    let err = _native_impl::unpack::unpack_one(&result, "nonexistent.txt");
    assert!(err.is_err());
}

/// Parse an archive into its header, seek entries, and payload sections.
#[allow(dead_code)]
fn parse_archive(data: &[u8]) -> (&[u8], Vec<_native_impl::entry::SeekEntry>, &[u8]) {
    use _native_impl::entry::*;
    let seek_offset = u64::from_le_bytes(data[16..24].try_into().unwrap()) as usize;
    let payload_offset = u64::from_le_bytes(data[24..32].try_into().unwrap()) as usize;
    let payload_size = u64::from_le_bytes(data[32..40].try_into().unwrap()) as usize;

    let (entries, _) = _native_impl::seek_table::decode(data, seek_offset).unwrap();
    let payload = &data[payload_offset..payload_offset + payload_size];
    (&data[..HEADER_SIZE], entries, payload)
}
