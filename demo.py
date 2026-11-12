#!/usr/bin/env python3
"""Classroom demonstrator for V1-V5 custom compressed packet files.

Usage:
  python demo.py                 # shows compressed sizes and performance summary
  python demo.py verify          # tests all 60 saved packets against originals
  python demo.py list            # names and file paths of the originals
  python demo.py compress ORIGINAL CODEC_ID OUTPUT_FILE
  python demo.py decompress COMPRESSED_PACKET OUTPUT_FILE

Examples:
  python demo.py compress original/skewed_DNA_12KB.txt v5_lz77_canonical recompressed.lz05
  python demo.py decompress recompressed.lz05 restored.txt

Run from the extracted package folder. Uses only Python standard library.
"""
import argparse, csv, hashlib, json
from pathlib import Path
from compression_codecs import CODECS
ROOT = Path(__file__).resolve().parent
METHODS = {
  'v1_fixed_length':'V1 Fixed-length',
  'v2_rle':'V2 RLE',
  'v3_huffman_tree':'V3 Huffman tree',
  'v4_huffman_canonical':'V4 Canonical Huffman',
  'v5_lz77_canonical':'V5 LZ77 + Canonical',
}
MAGIC = {b'FL01':'v1_fixed_length',b'RL02':'v2_rle',b'HF03':'v3_huffman_tree',b'HC04':'v4_huffman_canonical',b'LZ05':'v5_lz77_canonical'}

def sha(data):return hashlib.sha256(data).hexdigest()

def read_manifest():return json.loads((ROOT/'manifest.json').read_text(encoding='utf-8'))

def package_path(relative, scale):
    """Resolve a manifest path inside its scale-specific package directory."""
    relative = Path(relative)
    scale_dir = {'Standard': '1x'}.get(scale, scale)
    return ROOT / relative.parts[0] / scale_dir / Path(*relative.parts[1:])

def verify():
    manifest=read_manifest()
    count=0
    for dataset in manifest['datasets']:
        original=package_path(dataset['original_file'], dataset['scale']).read_bytes()
        assert len(original)==dataset['original_bytes'] and sha(original)==dataset['original_sha256'], dataset['name']
        for item in dataset['packets']:
            packet=package_path(item['file'], dataset['scale']).read_bytes()
            assert len(packet)==item['packet_bytes'] and sha(packet)==item['packet_sha256'], item['file']
            restored=CODECS[METHODS[item['codec_id']]][1](packet)
            assert restored==original,(dataset['name'],item['codec_id'])
            count+=1
    print(f'PASS: {count} / {count} byte-perfect decompressions; all packet and original SHA-256 hashes match.')

def listing():
    for item in read_manifest()['datasets']:
        path=package_path(item['original_file'], item['scale'])
        print(f"{str(path.relative_to(ROOT)):42s} {item['original_bytes']:>8,d} bytes  SHA256 {item['original_sha256'][:12]}...")

def summary():
    rows=list(csv.DictReader((ROOT/'compression_results.csv').open(newline='', encoding='utf-8')))
    print('Codec sizes (bytes). The outer ZIP delivery format is not a compression algorithm being benchmarked.')
    for dataset in read_manifest()['datasets']:
        print(f"\n{dataset['name']} — original {dataset['original_bytes']:,} bytes")
        for row in rows:
            if row['dataset'] == dataset['name']:
                print(f" {row['codec_id']:23s} {int(row['packet_bytes']):>9,d} bytes    {float(row['saved_pct']):+7.2f}% saved")
    print('\nRun `python demo.py verify` to prove every file decompresses byte-for-byte.')

def main():
    parser=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('action',nargs='?',choices=('show','list','verify','compress','decompress'),default='show')
    parser.add_argument('args',nargs='*')
    a=parser.parse_args()
    if a.action=='list':listing();return
    if a.action=='verify':verify();return
    if a.action=='show':summary();return
    if a.action=='compress':
        if len(a.args)!=3:parser.error('compress needs ORIGINAL CODEC_ID OUTPUT_FILE')
        source,method,output=a.args
        if method not in METHODS:parser.error('Unknown codec ID: '+method)
        data=Path(source).read_bytes();packet=CODECS[METHODS[method]][0](data)
        Path(output).write_bytes(packet)
        restored=CODECS[METHODS[method]][1](packet)
        assert restored==data
        print(f'Wrote {output}: {len(data):,} -> {len(packet):,} bytes; verified byte-perfect.')
    if a.action=='decompress':
        if len(a.args)!=2:parser.error('decompress needs PACKET OUTPUT_FILE')
        source,output=a.args
        packet=Path(source).read_bytes()
        method=MAGIC.get(packet[:4])
        if not method:parser.error('Not a supported V1-V5 packet')
        data=CODECS[METHODS[method]][1](packet)
        Path(output).write_bytes(data)
        print(f'Wrote {output}: {len(packet):,} -> {len(data):,} bytes; SHA256={sha(data)}')
if __name__=='__main__':main()
