# .woof Compressor Benchmark Report

Generated: 2026-05-21 18:27:16

Python: 3.12.6 (tags/v3.12.6:a4a2d2b, Sep  6 2024, 20:11:23) [MSC v.1940 64 bit (AMD64)]
zstandard: 0.25.0

Total scenarios: 7
Total benchmark configurations: 56

---
## Scenario: tiny

Entries: 2, Raw size: 3.71 KB

| Mode                     |    Arch Size |    Ratio |         Pack |       Unpack |             Speed(P/U) |     Mem(P) |     Mem(U) |   Chunks |
|------------------------|------------|--------|------------|------------|----------------------|----------|----------|--------|
| v1 (zlib, no compress)   |      3.79 KB |   0.978x |         7 us |         5 us |     540.2 / 682.9 MB/s |   11.00 KB |    7.00 KB |        0 |
| v1 (zlib, compress)      |     899.00 B |   4.221x |        59 us |        21 us |      61.2 / 176.5 MB/s |  294.00 KB |   25.00 KB |        0 |
| v2 (zstd+CDC, no compress) |      3.79 KB |   0.978x |         9 us |         5 us |     389.2 / 786.8 MB/s |    8.00 KB |    8.00 KB |        0 |
| v2 (zstd+CDC, compress)  |     938.00 B |   4.046x |        32 us |        13 us |     112.7 / 278.4 MB/s |    5.00 KB |    5.00 KB |        0 |
| ZIP (store)              |      3.92 KB |   0.945x |        48 us |        56 us |       74.8 / 64.7 MB/s |    5.00 KB |    7.00 KB |        0 |
| ZIP (deflate)            |    1020.00 B |   3.721x |       108 us |        60 us |       33.4 / 60.6 MB/s |  296.00 KB |   78.00 KB |        0 |
| RAR (store)              |      3.83 KB |   0.969x |     20.51 ms |     17.20 ms |         0.2 / 0.2 MB/s |   40.00 KB |   40.00 KB |        0 |
| RAR (compress)           |     957.00 B |   3.966x |     20.06 ms |     18.35 ms |         0.2 / 0.2 MB/s |   39.00 KB |   39.00 KB |        0 |

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
| v1 (zlib, no compress)   |     10.75 KB |   0.987x |         5 us |         4 us |   2159.5 / 2410.6 MB/s |   32.00 KB |   21.00 KB |        0 |
| v1 (zlib, compress)      |      1.92 KB |   5.537x |       161 us |        36 us |      64.5 / 292.0 MB/s |  296.00 KB |   35.00 KB |        0 |
| v2 (zstd+CDC, no compress) |     10.75 KB |   0.987x |         5 us |         4 us |   1884.6 / 2303.4 MB/s |   21.00 KB |   22.00 KB |        0 |
| v2 (zstd+CDC, compress)  |      1.98 KB |   5.359x |        64 us |        21 us |     163.0 / 493.6 MB/s |   10.00 KB |   13.00 KB |        0 |
| ZIP (store)              |     11.02 KB |   0.963x |        51 us |        61 us |     202.8 / 169.4 MB/s |   14.00 KB |   14.00 KB |        0 |
| ZIP (deflate)            |      2.16 KB |   4.905x |       245 us |       145 us |       42.3 / 71.5 MB/s |  298.00 KB |   86.00 KB |        0 |
| RAR (store)              |     10.93 KB |   0.971x |     21.46 ms |     17.78 ms |         0.5 / 0.6 MB/s |   39.00 KB |   39.00 KB |        0 |
| RAR (compress)           |      2.06 KB |   5.151x |     20.55 ms |     20.01 ms |         0.5 / 0.5 MB/s |   39.00 KB |   39.00 KB |        0 |

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
| v1 (zlib, no compress)   |      2.00 MB |   1.000x |      2.11 ms |       709 us |    948.0 / 2819.1 MB/s |    6.00 MB |    4.00 MB |        0 |
| v1 (zlib, compress)      |      1.95 MB |   1.027x |     54.05 ms |       866 us |     37.0 / 2307.9 MB/s |    5.84 MB |    3.95 MB |        0 |
| v2 (zstd+CDC, no compress) |      2.00 MB |   1.000x |      1.57 ms |      1.07 ms |   1277.0 / 1876.6 MB/s |    4.00 MB |    4.00 MB |        0 |
| v2 (zstd+CDC, compress)  |      1.95 MB |   1.027x |      3.29 ms |      1.17 ms |    606.8 / 1714.1 MB/s |    4.40 MB |    3.95 MB |        0 |
| ZIP (store)              |      2.00 MB |   0.999x |      1.91 ms |      1.17 ms |   1046.8 / 1711.2 MB/s |    2.19 MB |    2.01 MB |        0 |
| ZIP (deflate)            |      1.95 MB |   1.026x |     53.95 ms |      2.35 ms |      37.1 / 851.1 MB/s |    3.59 MB |    4.33 MB |        0 |
| RAR (store)              |      2.00 MB |   0.999x |     26.17 ms |     26.74 ms |       76.4 / 74.8 MB/s |    2.01 MB |    2.01 MB |        0 |
| RAR (compress)           |      1.95 MB |   1.026x |     68.63 ms |     28.22 ms |       29.1 / 70.8 MB/s |    1.96 MB |    2.01 MB |        0 |

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
| v1 (zlib, no compress)   |    273.45 KB |   0.998x |        71 us |        40 us |   3768.8 / 6661.4 MB/s |  820.00 KB |  548.00 KB |        0 |
| v1 (zlib, compress)      |     18.43 KB |  14.805x |      1.60 ms |       275 us |     166.8 / 967.9 MB/s |  312.00 KB |  310.00 KB |        0 |
| v2 (zstd+CDC, no compress) |    273.45 KB |   0.998x |        55 us |        26 us |  4809.7 / 10408.5 MB/s |  547.00 KB |  548.00 KB |        0 |
| v2 (zstd+CDC, compress)  |     18.90 KB |  14.438x |       361 us |       129 us |    738.3 / 2060.8 MB/s |   51.00 KB |  295.00 KB |        0 |
| ZIP (store)              |    274.87 KB |   0.993x |       568 us |       301 us |     468.8 / 885.5 MB/s |  316.00 KB |  285.00 KB |        0 |
| ZIP (deflate)            |     19.73 KB |  13.830x |      1.87 ms |       511 us |     142.7 / 521.6 MB/s |  320.00 KB |  357.00 KB |        0 |
| RAR (store)              |    275.01 KB |   0.992x |     23.68 ms |     22.47 ms |       11.3 / 11.9 MB/s |  284.00 KB |  287.00 KB |        0 |
| RAR (compress)           |     17.88 KB |  15.257x |     26.30 ms |     24.61 ms |       10.1 / 10.8 MB/s |   39.00 KB |  287.00 KB |        0 |

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
| v1 (zlib, no compress)   |     10.00 MB |   1.000x |     16.64 ms |      3.91 ms |    600.8 / 2554.5 MB/s |   30.00 MB |   20.00 MB |        0 |
| v1 (zlib, compress)      |     10.00 MB |   1.000x |    282.61 ms |      4.03 ms |     35.4 / 2480.0 MB/s |   30.00 MB |   20.00 MB |        0 |
| v2 (zstd+CDC, no compress) |     10.00 MB |   1.000x |     15.98 ms |      5.10 ms |    625.8 / 1960.1 MB/s |   20.00 MB |   20.00 MB |        0 |
| v2 (zstd+CDC, compress)  |     10.00 MB |   1.000x |     21.05 ms |      3.98 ms |    475.1 / 2511.3 MB/s |   21.00 MB |   20.00 MB |        0 |
| ZIP (store)              |     10.00 MB |   1.000x |     17.28 ms |      5.80 ms |    578.6 / 1722.9 MB/s |   10.13 MB |   10.01 MB |        0 |
| ZIP (deflate)            |     10.00 MB |   1.000x |    287.60 ms |     11.33 ms |      34.8 / 882.4 MB/s |   12.70 MB |   12.39 MB |        0 |
| RAR (store)              |     10.00 MB |   1.000x |     34.03 ms |     36.53 ms |     293.8 / 273.7 MB/s |   10.01 MB |   10.01 MB |        0 |
| RAR (compress)           |     10.00 MB |   1.000x |    184.73 ms |     36.27 ms |      54.1 / 275.7 MB/s |   10.01 MB |   10.01 MB |        0 |

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
| v1 (zlib, no compress)   |      2.59 MB |   1.000x |      4.68 ms |      1.25 ms |    554.0 / 2067.8 MB/s |    7.77 MB |    5.18 MB |        0 |
| v1 (zlib, compress)      |      2.51 MB |   1.033x |     68.61 ms |      1.16 ms |     37.8 / 2233.0 MB/s |    7.52 MB |    5.10 MB |        0 |
| v2 (zstd+CDC, no compress) |      2.59 MB |   1.000x |      3.53 ms |      1.13 ms |    734.7 / 2301.0 MB/s |    5.18 MB |    5.18 MB |        0 |
| v2 (zstd+CDC, compress)  |      2.51 MB |   1.033x |      5.83 ms |      1.30 ms |    444.8 / 1990.4 MB/s |    5.27 MB |    5.10 MB |        0 |
| ZIP (store)              |      2.59 MB |   0.999x |      5.03 ms |      1.72 ms |    515.2 / 1506.4 MB/s |    2.92 MB |    2.60 MB |        0 |
| ZIP (deflate)            |      2.51 MB |   1.032x |     69.07 ms |      2.50 ms |     37.5 / 1037.1 MB/s |    3.37 MB |    3.24 MB |        0 |
| RAR (store)              |      2.59 MB |   0.999x |     27.71 ms |     26.58 ms |       93.5 / 97.5 MB/s |    2.60 MB |    2.60 MB |        0 |
| RAR (compress)           |      2.51 MB |   1.033x |     69.38 ms |     31.36 ms |       37.3 / 82.6 MB/s |    2.52 MB |    2.60 MB |        0 |

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
| v1 (zlib, no compress)   |     33.65 MB |   1.000x |     58.08 ms |     17.30 ms |    579.3 / 1944.5 MB/s |  100.95 MB |   67.31 MB |        0 |
| v1 (zlib, compress)      |      6.87 MB |   4.895x |    695.73 ms |     71.51 ms |      48.4 / 470.5 MB/s |   20.62 MB |   48.05 MB |        0 |
| v2 (zstd+CDC, no compress) |     33.65 MB |   1.000x |     54.27 ms |     13.45 ms |    620.0 / 2501.2 MB/s |   67.30 MB |   67.31 MB |        0 |
| v2 (zstd+CDC, compress)  |      6.77 MB |   4.967x |     79.04 ms |     26.16 ms |    425.7 / 1286.1 MB/s |   13.55 MB |   42.64 MB |        0 |
| ZIP (store)              |     33.66 MB |   1.000x |     51.97 ms |     19.26 ms |    647.4 / 1746.5 MB/s |   36.97 MB |   33.69 MB |        0 |
| ZIP (deflate)            |      6.88 MB |   4.890x |    633.51 ms |     74.22 ms |      53.1 / 453.3 MB/s |    8.28 MB |   43.01 MB |        0 |
| RAR (store)              |     33.65 MB |   1.000x |     65.48 ms |    100.57 ms |     513.9 / 334.6 MB/s |   33.66 MB |   33.67 MB |        0 |
| RAR (compress)           |      6.15 MB |   5.469x |    547.74 ms |    117.34 ms |      61.4 / 286.7 MB/s |    6.16 MB |   33.67 MB |        0 |

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
- **Fastest pack**: 32 us (v2 compress=True)
- **Lowest memory**: 5.00 KB (v2 compress=True)