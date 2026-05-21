use std::collections::HashMap;

#[test]
fn test_roundtrip_no_compress() {
    let entries = vec![
        ("a.txt".into(), b"hello".to_vec()),
        ("b.txt".into(), b"world".to_vec()),
    ];

    let result = _native_impl::pack::pack_v2(entries, false, 3).unwrap();
    let unpacked = _native_impl::unpack::unpack_v2(&result).unwrap();

    let map: HashMap<&str, &[u8]> = unpacked
        .iter()
        .map(|(k, v)| (k.as_str(), v.as_slice()))
        .collect();
    assert_eq!(map.get("a.txt"), Some(&b"hello"[..]));
    assert_eq!(map.get("b.txt"), Some(&b"world"[..]));
}

#[test]
fn test_roundtrip_compress() {
    let data = "A".repeat(1000);
    let entries = vec![("compressible.txt".into(), data.as_bytes().to_vec())];

    let result = _native_impl::pack::pack_v2(entries, true, 3).unwrap();
    let unpacked = _native_impl::unpack::unpack_v2(&result).unwrap();

    assert_eq!(unpacked[0].1, data.as_bytes());
}

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

    let r1 = _native_impl::pack::pack_v2(entries1, false, 3).unwrap();
    let r2 = _native_impl::pack::pack_v2(entries2, false, 3).unwrap();
    assert_eq!(
        r1, r2,
        "output should be deterministic regardless of input order"
    );
}

#[test]
fn test_invalid_magic() {
    let data = b"NOTWOOF".to_vec();
    let result = _native_impl::unpack::unpack_v2(&data);
    assert!(result.is_err());
}
