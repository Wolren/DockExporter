# .woof Compressor Benchmark Report

Generated: 2026-05-21 19:36:39

Python: 3.12.6 (tags/v3.12.6:a4a2d2b, Sep  6 2024, 20:11:23) [MSC v.1940 64 bit (AMD64)]
zstandard: 0.25.0

Total scenarios: 7
Total benchmark configurations: 56

---
## Scenario: tiny

Entries: 2, Raw size: 3.71 KB

| Mode                     |    Arch Size |    Ratio |         Pack |       Unpack |             Speed(P/U) |     Mem(P) |     Mem(U) |   Chunks |
|------------------------|------------|--------|------------|------------|----------------------|----------|----------|--------|
| v1 (zlib, no compress)   |      3.79 KB |   0.978x |         6 us |         5 us |     650.2 / 798.4 MB/s |   11.00 KB |    8.00 KB |        0 |
| v1 (zlib, compress)      |     899.00 B |   4.221x |        54 us |        15 us |      67.6 / 236.5 MB/s |  294.00 KB |   25.00 KB |        0 |
| v2 (zstd+CDC, no compress) |      3.79 KB |   0.978x |         6 us |         4 us |     638.7 / 848.2 MB/s |   11.00 KB |    8.00 KB |        0 |
| v2 (zstd+CDC, compress)  |     938.00 B |   4.046x |        23 us |        14 us |     160.4 / 254.9 MB/s |    6.00 KB |    6.00 KB |        0 |
| ZIP (store)              |      3.92 KB |   0.945x |        38 us |        42 us |       95.9 / 85.5 MB/s |    5.00 KB |    6.00 KB |        0 |
| ZIP (deflate)            |    1020.00 B |   3.721x |        92 us |        53 us |       39.5 / 68.4 MB/s |  296.00 KB |   78.00 KB |        0 |
| RAR (store)              |      3.83 KB |   0.969x |     20.16 ms |     17.11 ms |         0.2 / 0.2 MB/s |   39.00 KB |   39.00 KB |        0 |
| RAR (compress)           |     957.00 B |   3.966x |     20.12 ms |     18.37 ms |         0.2 / 0.2 MB/s |   39.00 KB |   39.00 KB |        0 |

**Ratio comparison (higher = better):**

| Mode | Ratio |
|------|-------|
| v1 (zlib, compress) | 4.22x |
| v2 (zstd+CDC, compress) | 4.05x |
| RAR (compress) | 3.97x |
| ZIP (deflate) | 3.72x |
| v1 (zlib, no compress) | 0.98x |
| v2 (zstd+CDC, no compress) | 0.98x |
| RAR (store) | 0.97x |
| ZIP (store) | 0.94x |

---
## Scenario: small

Entries: 4, Raw size: 10.61 KB

| Mode                     |    Arch Size |    Ratio |         Pack |       Unpack |             Speed(P/U) |     Mem(P) |     Mem(U) |   Chunks |
|------------------------|------------|--------|------------|------------|----------------------|----------|----------|--------|
| v1 (zlib, no compress)   |     10.75 KB |   0.987x |        10 us |         9 us |   1012.9 / 1110.6 MB/s |   32.00 KB |   22.00 KB |        0 |
| v1 (zlib, compress)      |      1.92 KB |   5.537x |       132 us |        42 us |      78.8 / 245.4 MB/s |  296.00 KB |   35.00 KB |        0 |
| v2 (zstd+CDC, no compress) |     10.75 KB |   0.987x |         7 us |         7 us |   1439.7 / 1433.0 MB/s |   32.00 KB |   22.00 KB |        0 |
| v2 (zstd+CDC, compress)  |      1.98 KB |   5.359x |        52 us |        21 us |     197.8 / 494.4 MB/s |   10.00 KB |   14.00 KB |        0 |
| ZIP (store)              |     11.02 KB |   0.963x |        52 us |        69 us |     198.6 / 149.6 MB/s |   14.00 KB |   14.00 KB |        0 |
| ZIP (deflate)            |      2.16 KB |   4.905x |       210 us |        98 us |      49.4 / 106.0 MB/s |  298.00 KB |   86.00 KB |        0 |
| RAR (store)              |     10.93 KB |   0.971x |     88.34 ms |     20.93 ms |         0.1 / 0.5 MB/s |   39.00 KB |   39.00 KB |        0 |
| RAR (compress)           |      2.06 KB |   5.151x |     24.12 ms |     20.42 ms |         0.4 / 0.5 MB/s |   39.00 KB |   39.00 KB |        0 |

**Ratio comparison (higher = better):**

| Mode | Ratio |
|------|-------|
| v1 (zlib, compress) | 5.54x |
| v2 (zstd+CDC, compress) | 5.36x |
| RAR (compress) | 5.15x |
| ZIP (deflate) | 4.91x |
| v1 (zlib, no compress) | 0.99x |
| v2 (zstd+CDC, no compress) | 0.99x |
| RAR (store) | 0.97x |
| ZIP (store) | 0.96x |

---
## Scenario: standard

Entries: 16, Raw size: 2.00 MB

| Mode                     |    Arch Size |    Ratio |         Pack |       Unpack |             Speed(P/U) |     Mem(P) |     Mem(U) |   Chunks |
|------------------------|------------|--------|------------|------------|----------------------|----------|----------|--------|
| v1 (zlib, no compress)   |      2.00 MB |   1.000x |      2.98 ms |       763 us |    671.3 / 2619.4 MB/s |    6.00 MB |    4.00 MB |        0 |
| v1 (zlib, compress)      |      1.95 MB |   1.027x |     55.42 ms |      1.10 ms |     36.1 / 1811.9 MB/s |    5.84 MB |    3.95 MB |        0 |
| v2 (zstd+CDC, no compress) |      2.00 MB |   1.000x |      2.29 ms |       980 us |    873.5 / 2040.7 MB/s |    6.00 MB |    4.00 MB |        0 |
| v2 (zstd+CDC, compress)  |      1.95 MB |   1.027x |      4.49 ms |      1.04 ms |    445.4 / 1930.3 MB/s |    6.34 MB |    3.95 MB |        0 |
| ZIP (store)              |      2.00 MB |   0.999x |      2.49 ms |      1.65 ms |    802.3 / 1215.3 MB/s |    2.19 MB |    2.01 MB |        0 |
| ZIP (deflate)            |      1.95 MB |   1.026x |     54.90 ms |      2.36 ms |      36.4 / 847.5 MB/s |    3.59 MB |    4.33 MB |        0 |
| RAR (store)              |      2.00 MB |   0.999x |     24.18 ms |     28.72 ms |       82.7 / 69.6 MB/s |    2.01 MB |    2.01 MB |        0 |
| RAR (compress)           |      1.95 MB |   1.026x |     66.81 ms |     30.17 ms |       29.9 / 66.3 MB/s |    1.96 MB |    2.01 MB |        0 |

**Ratio comparison (higher = better):**

| Mode | Ratio |
|------|-------|
| v1 (zlib, compress) | 1.03x |
| v2 (zstd+CDC, compress) | 1.03x |
| ZIP (deflate) | 1.03x |
| RAR (compress) | 1.03x |
| v1 (zlib, no compress) | 1.00x |
| v2 (zstd+CDC, no compress) | 1.00x |
| ZIP (store) | 1.00x |
| RAR (store) | 1.00x |

---
## Scenario: text_heavy

Entries: 20, Raw size: 272.85 KB

| Mode                     |    Arch Size |    Ratio |         Pack |       Unpack |             Speed(P/U) |     Mem(P) |     Mem(U) |   Chunks |
|------------------------|------------|--------|------------|------------|----------------------|----------|----------|--------|
| v1 (zlib, no compress)   |    273.45 KB |   0.998x |       135 us |        33 us |   1969.9 / 8148.5 MB/s |  854.00 KB |  549.00 KB |        0 |
| v1 (zlib, compress)      |     18.43 KB |  14.805x |      1.39 ms |       315 us |     191.7 / 844.9 MB/s |  312.00 KB |  310.00 KB |        0 |
| v2 (zstd+CDC, no compress) |    273.45 KB |   0.998x |        60 us |        40 us |   4443.4 / 6683.7 MB/s |  854.00 KB |  549.00 KB |        0 |
| v2 (zstd+CDC, compress)  |     18.90 KB |  14.438x |       266 us |       206 us |   1000.3 / 1291.6 MB/s |   73.00 KB |  295.00 KB |        0 |
| ZIP (store)              |    274.87 KB |   0.993x |       282 us |       294 us |     943.3 / 907.7 MB/s |  316.00 KB |  285.00 KB |        0 |
| ZIP (deflate)            |     19.73 KB |  13.830x |      2.47 ms |       873 us |     107.8 / 305.1 MB/s |  320.00 KB |  357.00 KB |        0 |
| RAR (store)              |    275.01 KB |   0.992x |     23.29 ms |     23.37 ms |       11.4 / 11.4 MB/s |  283.00 KB |  286.00 KB |        0 |
| RAR (compress)           |     17.88 KB |  15.257x |     26.01 ms |     24.09 ms |       10.2 / 11.1 MB/s |   39.00 KB |  287.00 KB |        0 |

**Ratio comparison (higher = better):**

| Mode | Ratio |
|------|-------|
| RAR (compress) | 15.26x |
| v1 (zlib, compress) | 14.80x |
| v2 (zstd+CDC, compress) | 14.44x |
| ZIP (deflate) | 13.83x |
| v1 (zlib, no compress) | 1.00x |
| v2 (zstd+CDC, no compress) | 1.00x |
| ZIP (store) | 0.99x |
| RAR (store) | 0.99x |

---
## Scenario: binary_heavy

Entries: 10, Raw size: 10.00 MB

| Mode                     |    Arch Size |    Ratio |         Pack |       Unpack |             Speed(P/U) |     Mem(P) |     Mem(U) |   Chunks |
|------------------------|------------|--------|------------|------------|----------------------|----------|----------|--------|
| v1 (zlib, no compress)   |     10.00 MB |   1.000x |     18.37 ms |      4.60 ms |    544.4 / 2172.1 MB/s |   30.13 MB |   20.00 MB |        0 |
| v1 (zlib, compress)      |     10.00 MB |   1.000x |    290.74 ms |      4.51 ms |     34.4 / 2214.9 MB/s |   30.13 MB |   20.00 MB |        0 |
| v2 (zstd+CDC, no compress) |     10.00 MB |   1.000x |     17.31 ms |      4.54 ms |    577.6 / 2201.5 MB/s |   30.13 MB |   20.00 MB |        0 |
| v2 (zstd+CDC, compress)  |     10.00 MB |   1.000x |     21.68 ms |      4.45 ms |    461.3 / 2248.7 MB/s |   31.13 MB |   20.00 MB |        0 |
| ZIP (store)              |     10.00 MB |   1.000x |     16.00 ms |      6.14 ms |    624.9 / 1630.0 MB/s |   10.13 MB |   10.01 MB |        0 |
| ZIP (deflate)            |     10.00 MB |   1.000x |    287.47 ms |     10.56 ms |      34.8 / 946.8 MB/s |   12.70 MB |   12.39 MB |        0 |
| RAR (store)              |     10.00 MB |   1.000x |     34.90 ms |     37.77 ms |     286.5 / 264.8 MB/s |   10.01 MB |   10.01 MB |        0 |
| RAR (compress)           |     10.00 MB |   1.000x |    189.91 ms |     38.81 ms |      52.7 / 257.7 MB/s |   10.01 MB |   10.01 MB |        0 |

**Ratio comparison (higher = better):**

| Mode | Ratio |
|------|-------|
| v1 (zlib, no compress) | 1.00x |
| v1 (zlib, compress) | 1.00x |
| v2 (zstd+CDC, no compress) | 1.00x |
| v2 (zstd+CDC, compress) | 1.00x |
| ZIP (store) | 1.00x |
| ZIP (deflate) | 1.00x |
| RAR (store) | 1.00x |
| RAR (compress) | 1.00x |

---
## Scenario: mixed

Entries: 20, Raw size: 2.59 MB

| Mode                     |    Arch Size |    Ratio |         Pack |       Unpack |             Speed(P/U) |     Mem(P) |     Mem(U) |   Chunks |
|------------------------|------------|--------|------------|------------|----------------------|----------|----------|--------|
| v1 (zlib, no compress)   |      2.59 MB |   1.000x |      5.00 ms |      1.51 ms |    518.0 / 1715.9 MB/s |    8.10 MB |    5.18 MB |        0 |
| v1 (zlib, compress)      |      2.51 MB |   1.033x |     68.97 ms |      1.42 ms |     37.6 / 1823.3 MB/s |    7.84 MB |    5.10 MB |        0 |
| v2 (zstd+CDC, no compress) |      2.59 MB |   1.000x |      5.80 ms |      1.44 ms |    446.4 / 1798.1 MB/s |    8.10 MB |    5.19 MB |        0 |
| v2 (zstd+CDC, compress)  |      2.51 MB |   1.033x |      5.99 ms |      1.38 ms |    432.6 / 1880.8 MB/s |    8.09 MB |    5.10 MB |        0 |
| ZIP (store)              |      2.59 MB |   0.999x |      4.43 ms |      2.29 ms |    584.6 / 1131.5 MB/s |    2.92 MB |    2.60 MB |        0 |
| ZIP (deflate)            |      2.51 MB |   1.032x |     69.79 ms |      2.32 ms |     37.1 / 1116.8 MB/s |    3.37 MB |    3.24 MB |        0 |
| RAR (store)              |      2.59 MB |   0.999x |     26.00 ms |     28.66 ms |       99.6 / 90.4 MB/s |    2.60 MB |    2.60 MB |        0 |
| RAR (compress)           |      2.51 MB |   1.033x |     70.36 ms |     29.22 ms |       36.8 / 88.7 MB/s |    2.52 MB |    2.60 MB |        0 |

**Ratio comparison (higher = better):**

| Mode | Ratio |
|------|-------|
| v1 (zlib, compress) | 1.03x |
| v2 (zstd+CDC, compress) | 1.03x |
| RAR (compress) | 1.03x |
| ZIP (deflate) | 1.03x |
| v1 (zlib, no compress) | 1.00x |
| v2 (zstd+CDC, no compress) | 1.00x |
| ZIP (store) | 1.00x |
| RAR (store) | 1.00x |

---
## Scenario: real_data

Entries: 70, Raw size: 33.65 MB

| Mode                     |    Arch Size |    Ratio |         Pack |       Unpack |             Speed(P/U) |     Mem(P) |     Mem(U) |   Chunks |
|------------------------|------------|--------|------------|------------|----------------------|----------|----------|--------|
| v1 (zlib, no compress)   |     33.65 MB |   1.000x |     66.48 ms |     14.34 ms |    506.1 / 2347.0 MB/s |  105.15 MB |   67.31 MB |        0 |
| v1 (zlib, compress)      |      6.87 MB |   4.895x |    647.13 ms |     74.86 ms |      52.0 / 449.5 MB/s |   21.48 MB |   48.05 MB |        0 |
| v2 (zstd+CDC, no compress) |     33.65 MB |   1.000x |     60.19 ms |     14.84 ms |    559.0 / 2267.2 MB/s |  105.15 MB |   67.31 MB |        0 |
| v2 (zstd+CDC, compress)  |      6.77 MB |   4.967x |     74.82 ms |     26.87 ms |    449.7 / 1252.4 MB/s |   21.17 MB |   42.64 MB |        0 |
| ZIP (store)              |     33.66 MB |   1.000x |     51.32 ms |     20.38 ms |    655.6 / 1651.3 MB/s |   36.97 MB |   33.69 MB |        0 |
| ZIP (deflate)            |      6.88 MB |   4.890x |    625.61 ms |     78.64 ms |      53.8 / 427.9 MB/s |    8.28 MB |   43.01 MB |        0 |
| RAR (store)              |     33.65 MB |   1.000x |     67.53 ms |    111.74 ms |     498.3 / 301.1 MB/s |   33.66 MB |   33.67 MB |        0 |
| RAR (compress)           |      6.15 MB |   5.469x |    558.77 ms |    118.49 ms |      60.2 / 284.0 MB/s |    6.16 MB |   33.67 MB |        0 |

**Ratio comparison (higher = better):**

| Mode | Ratio |
|------|-------|
| RAR (compress) | 5.47x |
| v2 (zstd+CDC, compress) | 4.97x |
| v1 (zlib, compress) | 4.89x |
| ZIP (deflate) | 4.89x |
| v1 (zlib, no compress) | 1.00x |
| v2 (zstd+CDC, no compress) | 1.00x |
| ZIP (store) | 1.00x |
| RAR (store) | 1.00x |

---
## Cross-Scenario Summary (Compression Ratio)

| Scenario             |   v1 (zlib, no compress) |   v1 (zlib, compress) |   v2 (zstd+CDC, no compress) |   v2 (zstd+CDC, compress) |      ZIP (store) |    ZIP (deflate) |      RAR (store) |   RAR (compress) |
|--------------------|------------------------|---------------------|----------------------------|-------------------------|----------------|----------------|----------------|----------------|
| tiny                 |                    0.978 |                 4.221 |                        0.978 |                     4.046 |            0.945 |            3.721 |            0.969 |            3.966 |
| small                |                    0.987 |                 5.537 |                        0.987 |                     5.359 |            0.963 |            4.905 |            0.971 |            5.151 |
| standard             |                    1.000 |                 1.027 |                        1.000 |                     1.027 |            0.999 |            1.026 |            0.999 |            1.026 |
| text_heavy           |                    0.998 |                14.805 |                        0.998 |                    14.438 |            0.993 |           13.830 |            0.992 |           15.257 |
| binary_heavy         |                    1.000 |                 1.000 |                        1.000 |                     1.000 |            1.000 |            1.000 |            1.000 |            1.000 |
| mixed                |                    1.000 |                 1.033 |                        1.000 |                     1.033 |            0.999 |            1.032 |            0.999 |            1.033 |
| real_data            |                    1.000 |                 4.895 |                        1.000 |                     4.967 |            1.000 |            4.890 |            1.000 |            5.469 |

---
## Recommendations
- **Best compression ratio**: 15.257x (rar compress=True)
- **Fastest pack**: 23 us (v2 compress=True)
- **Lowest memory**: 5.00 KB (zip compress=False)