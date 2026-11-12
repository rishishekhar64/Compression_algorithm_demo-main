# Problem 8 — Compression Demo (Standard)

This package has **four original files and 20 real compressed packets** created by the five educational codecs in the verified V4 implementation. All 20 packets were decoded and compared byte-for-byte with their originals. **These formats are custom `.fl01/.rl02/.hf03/.hc04/.lz05` binary packets, not ordinary ZIP or standard gzip/DEFLATE files.** You need `demo.py` + `compression_codecs.py` to decode them.

## Quick demonstration (Python 3.11+; no external dependencies)

Unzip this package and open a terminal inside the extracted folder.

```
python demo.py
python demo.py verify
python demo.py list
python demo.py decompress compressed/v5_lz77_canonical/long_runs_10KB.lz05 recovered.txt
```

The final line restores one file; you can compare `recovered.txt` with `original/long_runs_10KB.txt`.

To compress any file yourself:

```
python demo.py compress original/long_runs_10KB.txt v5_lz77_canonical my_output.lz05
python demo.py decompress my_output.lz05 restored.txt
```

Valid codec IDs: `v1_fixed_length`, `v2_rle`, `v3_huffman_tree`, `v4_huffman_canonical`, `v5_lz77_canonical`.

## Inside the package

- `original/` — the four exact input files.
- `compressed/<codec>/` — the generated binary packets for each input (5 × 4 = 20).
- `compression_results.csv` — packet sizes, bytes saved, ratios, timings for a single run (including custom container headers).
- `compression_comparison.png` — simple ready-to-project size comparison (log scale); check CSV for exact values.
- `manifest.json` — SHA-256 checksums for every original and compressed file.
- `packet_hex_preview.txt` — first bytes of each compressed packet in hexadecimal to show the class.
- `demo.py`, `compression_codecs.py` — runnable encoder/decoder and verification.

## Dataset methodology

Original V4 pinned benchmark inputs, unchanged: 10 KB long runs; 12 KB seeded skewed DNA; 50 KiB of real Python source; 10 KB of `os.urandom` bytes. Their hashes match the V4 manifest.

**Interpretation:** RLE works well for long uniform runs but can expand ordinary text and random bytes. Huffman favors skewed symbol distributions. LZ77 finds repeated sequences, but the educational V5's tokenization and header overhead are not competitive on every input. Compressed sizes include header metadata and padding, so a compressed packet may be larger than its input.

**Important:** The outer `.zip` archive is only a delivery bundle. The real compressor outputs are the individual packet files inside it. The benchmark speed numbers depend on this machine; input/output hashes and compressed sizes can be independently verified.

## Credit
Courtesy to my group member:
Radit, Eduardo and Rishi
