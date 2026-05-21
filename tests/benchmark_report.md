# .woof Compressor Benchmark Report

Generated: 2026-05-21 17:58:41

Python: 3.12.6 (tags/v3.12.6:a4a2d2b, Sep  6 2024, 20:11:23) [MSC v.1940 64 bit (AMD64)]
zstandard: 0.25.0

Total scenarios: 2
Total benchmark configurations: 6

---
## Scenario: tiny

Entries: 2, Raw size: 3.71 KB

| Mode                     |    Arch Size |    Ratio |         Pack |       Unpack |             Speed(P/U) |     Mem(P) |     Mem(U) |   Chunks |
|------------------------|------------|--------|------------|------------|----------------------|----------|----------|--------|
| v1 (zlib, compress)      |     967.00 B |   3.925x |       164 us |        70 us |       22.0 / 52.1 MB/s |  294.00 KB |   25.00 KB |        0 |
| v2 (zstd+CDC, compress)  |      1.08 KB |   3.431x |      2.36 ms |        87 us |        1.5 / 41.6 MB/s |    9.00 KB |    7.00 KB |        2 |
| ZIP (deflate)            |    1020.00 B |   3.721x |       233 us |       629 us |        15.6 / 5.8 MB/s |  296.00 KB |   78.00 KB |        0 |

**Ratio comparison (higher = better):**

| Mode | Ratio | Bar |
|------|-------|-----|
| v1 (zlib, compress) | 3.92x | #################### |
| ZIP (deflate) | 3.72x | ##################-- |
| v2 (zstd+CDC, compress) | 3.43x | #################--- |

---
## Scenario: real_data

Entries: 6, Raw size: 2.80 MB

| Mode                     |    Arch Size |    Ratio |         Pack |       Unpack |             Speed(P/U) |     Mem(P) |     Mem(U) |   Chunks |
|------------------------|------------|--------|------------|------------|----------------------|----------|----------|--------|
| v1 (zlib, compress)      |      2.79 MB |   1.005x |    102.43 ms |     96.46 ms |       27.4 / 29.1 MB/s |   11.17 MB |    6.46 MB |        0 |
| v2 (zstd+CDC, compress)  |      2.80 MB |   1.003x |    409.07 ms |     96.11 ms |        6.9 / 29.2 MB/s |   11.36 MB |    8.57 MB |        4 |
| ZIP (deflate)            |      2.45 MB |   1.146x |     98.14 ms |     13.79 ms |      28.6 / 203.3 MB/s |    8.01 MB |   10.24 MB |        0 |

**Ratio comparison (higher = better):**

| Mode | Ratio | Bar |
|------|-------|-----|
| ZIP (deflate) | 1.15x | #################### |
| v1 (zlib, compress) | 1.00x | #################--- |
| v2 (zstd+CDC, compress) | 1.00x | #################--- |

---
## Cross-Scenario Summary (Compression Ratio)

| Scenario             |   v1 (zlib, compress) |   v2 (zstd+CDC, compress) |    ZIP (deflate) |
|--------------------|---------------------|-------------------------|----------------|
| tiny                 |                 3.925 |                     3.431 |            3.721 |
| real_data            |                 1.005 |                     1.003 |            1.146 |

---
## Recommendations
- **Best compression ratio**: 3.925x (v1 compress=True)
- **Fastest pack**: 164 us (v1 compress=True)
- **Lowest memory**: 9.00 KB (v2 compress=True)