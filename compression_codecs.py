from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import dataclass
import heapq
import math
import struct
from typing import Optional


class BitWriter:
    def __init__(self):
        self.data = bytearray()
        self.accumulator = 0
        self.filled = 0
        self.bits_written = 0

    def write(self, value: int, width: int) -> None:
        if width < 0 or value < 0 or value >= (1 << width):
            raise ValueError(f"Value {value} does not fit in {width} bits")
        self.bits_written += width
        for bit_index in range(width - 1, -1, -1):
            self.accumulator = (self.accumulator << 1) | ((value >> bit_index) & 1)
            self.filled += 1
            if self.filled == 8:
                self.data.append(self.accumulator)
                self.accumulator = 0
                self.filled = 0

    def finish(self) -> bytes:
        if self.filled:
            self.data.append(self.accumulator << (8 - self.filled))
            self.accumulator = 0
            self.filled = 0
        return bytes(self.data)


class BitReader:
    def __init__(self, payload: bytes):
        self.data = payload
        self.pos = 0

    def read(self, width: int) -> int:
        if width < 0 or self.pos + width > 8 * len(self.data):
            raise ValueError("Truncated bitstream")
        value = 0
        for _ in range(width):
            byte = self.data[self.pos >> 3]
            value = (value << 1) | ((byte >> (7 - (self.pos & 7))) & 1)
            self.pos += 1
        return value


@dataclass(slots=True)
class HuffNode:
    weight: int
    symbol: Optional[int] = None
    left: Optional['HuffNode'] = None
    right: Optional['HuffNode'] = None


def huffman_tree(frequencies: dict[int, int]) -> Optional[HuffNode]:
    """Deterministic O(m log m) binary min-heap Huffman construction."""
    heap = []
    serial = 0
    for symbol, count in sorted(frequencies.items()):
        if count <= 0:
            raise ValueError("Frequencies must be positive")
        leaf = HuffNode(count, symbol)
        heapq.heappush(heap, (count, symbol, serial, leaf))
        serial += 1
    while len(heap) > 1:
        wa, mina, _, left = heapq.heappop(heap)
        wb, minb, _, right = heapq.heappop(heap)
        parent = HuffNode(wa + wb, None, left, right)
        heapq.heappush(heap, (wa + wb, min(mina, minb), serial, parent))
        serial += 1
    return heap[0][-1] if heap else None


def tree_codes(node: HuffNode) -> dict[int, tuple[int, int]]:
    codes = {}

    def visit(n: HuffNode, code: int, depth: int) -> None:
        if n.symbol is not None:
            codes[n.symbol] = (code, depth or 1)
        else:
            visit(n.left, code << 1, depth + 1)
            visit(n.right, (code << 1) | 1, depth + 1)

    visit(node, 0, 0)
    return codes


def canonical_codes(lengths: dict[int, int]) -> dict[int, tuple[int, int]]:
    """Sort (length, symbol); first code 0, others (code+1) << length jump."""
    if not lengths:
        return {}
    sorted_items = sorted(lengths.items(), key=lambda e: (e[1], e[0]))
    output = {}
    prior_length = sorted_items[0][1]
    if not 1 <= prior_length <= 255:
        raise ValueError("Invalid Huffman code length")
    code = 0
    for index, (symbol, length) in enumerate(sorted_items):
        if index:
            code = (code + 1) << (length - prior_length)
        if length <= 0 or length > 255 or code >= (1 << length):
            raise ValueError("Invalid / non-prefix-free code lengths")
        output[symbol] = (code, length)
        prior_length = length
    return output


def build_canonical(data: list[int] | bytes) -> dict[int, tuple[int, int]]:
    counts = Counter(data)
    if not counts:
        return {}
    root = huffman_tree(counts)
    lengths = {symbol: width for symbol, (_, width) in tree_codes(root).items()}
    return canonical_codes(lengths)


def serialize_lengths(codes: dict[int, tuple[int, int]], symbol_width: int) -> bytes:
    if len(codes) > 65535:
        raise ValueError("Too many symbols")
    result = bytearray(struct.pack('>H', len(codes)))
    for symbol in sorted(codes):
        result.extend(int(symbol).to_bytes(symbol_width, 'big'))
        result.append(codes[symbol][1])
    return bytes(result)


def parse_lengths(packet: bytes, cursor: int, symbol_width: int):
    if cursor + 2 > len(packet):
        raise ValueError("Truncated codebook")
    m = struct.unpack_from('>H', packet, cursor)[0]
    cursor += 2
    lengths = {}
    for _ in range(m):
        if cursor + symbol_width + 1 > len(packet):
            raise ValueError("Truncated codebook entries")
        symbol = int.from_bytes(packet[cursor:cursor + symbol_width], 'big')
        length = packet[cursor + symbol_width]
        cursor += symbol_width + 1
        if symbol in lengths:
            raise ValueError("Duplicate codebook symbol")
        lengths[symbol] = length
    return canonical_codes(lengths), cursor


def decode_one(reader: BitReader, codes: dict[int, tuple[int, int]]) -> int:
    if not codes:
        raise ValueError("Attempt to decode with empty table")
    decoding = {(width, bits): sym for sym, (bits, width) in codes.items()}
    maximum = max(width for _, width in codes.values())
    value = 0
    for width in range(1, maximum + 1):
        value = (value << 1) | reader.read(1)
        if (width, value) in decoding:
            return decoding[(width, value)]
    raise ValueError("Invalid Huffman codeword")


def decoder_for(codes: dict[int, tuple[int, int]]):
    """Precompute lookup once rather than per decoded symbol."""
    lookup = {(width, code): sym for sym, (code, width) in codes.items()}
    maximum = max((width for _, width in codes.values()), default=0)

    def get(reader: BitReader) -> int:
        value = 0
        for width in range(1, maximum + 1):
            value = (value << 1) | reader.read(1)
            if (width, value) in lookup:
                return lookup[width, value]
        raise ValueError("Invalid canonical bitstring")
    return get


def v1_fixed_length_compress(data: bytes) -> bytes:
    alphabet = bytes(sorted(set(data)))
    m = len(alphabet)
    width = (m - 1).bit_length() if m else 0
    writer = BitWriter()
    index = {symbol: i for i, symbol in enumerate(alphabet)}
    for symbol in data:
        writer.write(index[symbol], width)
    return b'FL01' + struct.pack('>IHB', len(data), m, width) + alphabet + writer.finish()


def v1_fixed_length_decompress(packet: bytes) -> bytes:
    if len(packet) < 11 or packet[:4] != b'FL01':
        raise ValueError('Invalid fixed-length packet')
    n, m, width = struct.unpack_from('>IHB', packet, 4)
    if m > 256 or width != ((m - 1).bit_length() if m else 0) or (n > 0 and m == 0):
        raise ValueError('Invalid alphabet metadata')
    if len(packet) < 11 + m:
        raise ValueError('Truncated alphabet')
    alphabet = packet[11:11 + m]
    reader = BitReader(packet[11 + m:])
    result = bytearray()
    for _ in range(n):
        index = reader.read(width)
        if index >= m:
            raise ValueError('Invalid symbol index')
        result.append(alphabet[index])
    return bytes(result)


def v2_rle_compress(data: bytes) -> bytes:
    """7-bit run count (1..127) + 8-bit byte literal, packed into 15-bit runs.

    Handworked Part A uses 3-bit symbols because its alphabet has only 6 letters.
    """
    writer = BitWriter()
    i = 0
    while i < len(data):
        count = 1
        while i + count < len(data) and count < 127 and data[i + count] == data[i]:
            count += 1
        writer.write(count, 7)
        writer.write(data[i], 8)
        i += count
    return b'RL02' + struct.pack('>I', len(data)) + writer.finish()


def v2_rle_decompress(packet: bytes) -> bytes:
    if len(packet) < 8 or packet[:4] != b'RL02':
        raise ValueError('Invalid RLE packet')
    n = struct.unpack_from('>I', packet, 4)[0]
    reader = BitReader(packet[8:])
    decoded = bytearray()
    while len(decoded) < n:
        count, symbol = reader.read(7), reader.read(8)
        if count == 0 or len(decoded) + count > n:
            raise ValueError('Invalid RLE run')
        decoded.extend(bytes([symbol]) * count)
    return bytes(decoded)


def write_tree(node: HuffNode, writer: BitWriter) -> None:
    if node.symbol is not None:
        writer.write(1, 1)
        writer.write(node.symbol, 8)
    else:
        writer.write(0, 1)
        write_tree(node.left, writer)
        write_tree(node.right, writer)


def read_tree(reader: BitReader) -> HuffNode:
    if reader.read(1):
        return HuffNode(0, reader.read(8))
    left = read_tree(reader)
    right = read_tree(reader)
    return HuffNode(0, None, left, right)


def v3_huffman_tree_compress(data: bytes) -> bytes:
    writer = BitWriter()
    if data:
        root = huffman_tree(Counter(data))
        write_tree(root, writer)
        codes = tree_codes(root)
        for symbol in data:
            code, width = codes[symbol]
            writer.write(code, width)
    return b'HF03' + struct.pack('>I', len(data)) + writer.finish()


def v3_huffman_tree_decompress(packet: bytes) -> bytes:
    if len(packet) < 8 or packet[:4] != b'HF03':
        raise ValueError('Invalid Huffman tree packet')
    n = struct.unpack_from('>I', packet, 4)[0]
    if n == 0:
        return b''
    reader = BitReader(packet[8:])
    root = read_tree(reader)
    result = bytearray()
    for _ in range(n):
        node = root
        if node.symbol is not None:
            if reader.read(1) != 0:
                raise ValueError('Invalid single-symbol code')
        else:
            while node.symbol is None:
                node = node.right if reader.read(1) else node.left
        result.append(node.symbol)
    return bytes(result)


def v4_huffman_canonical_compress(data: bytes) -> bytes:
    codes = build_canonical(data)
    writer = BitWriter()
    for symbol in data:
        bits, width = codes[symbol]
        writer.write(bits, width)
    return (b'HC04' + struct.pack('>I', len(data)) +
            serialize_lengths(codes, 1) + writer.finish())


def v4_huffman_canonical_decompress(packet: bytes) -> bytes:
    if len(packet) < 8 or packet[:4] != b'HC04':
        raise ValueError('Invalid canonical Huffman packet')
    n = struct.unpack_from('>I', packet, 4)[0]
    codes, cursor = parse_lengths(packet, 8, 1)
    read_symbol = decoder_for(codes)
    reader = BitReader(packet[cursor:])
    return bytes(read_symbol(reader) for _ in range(n))


def lz77_tokens(data: bytes, window: int = 4096, lookahead: int = 32):
    """Longest-match LZ77 triples (offset,length,next_literal).

    Full exact search of matching three-byte-prefix candidate positions in the
    previous W bytes; matching from 1 or 2 bytes uses last seen positions.
    Supports overlapping back-references and consumes a final literal always.
    """
    if window < 1 or lookahead < 1:
        raise ValueError('Window and lookahead must be positive')
    n = len(data)
    p = 0
    indexed_until = 0
    expired_until = 0
    trigrams = defaultdict(deque)
    last_one = {}
    last_two = {}
    output = []
    while p < n:
        # Add all positions processed by preceding token, even if referenced.
        while indexed_until < p:
            j = indexed_until
            last_one[data[j]] = j
            if j + 2 <= n:
                last_two[data[j:j+2]] = j
            if j + 3 <= n:
                trigrams[data[j:j+3]].append(j)
            indexed_until += 1
        # Maintain only positions starting in S[max(0,p-W)..p-1].
        oldest_valid = max(0, p-window)
        while expired_until < oldest_valid:
            j = expired_until
            if j + 3 <= n:
                key = data[j:j+3]
                positions = trigrams.get(key)
                if positions and positions[0] == j:
                    positions.popleft()
                    if not positions:
                        del trigrams[key]
            expired_until += 1
        maximum = min(lookahead, n-p-1)  # reserve a final next_char
        best_len = 0
        best_off = 0
        if maximum >= 3:
            for j in reversed(trigrams.get(data[p:p+3], ())):
                if j < oldest_valid:
                    break
                length = 3
                while length < maximum and data[j+length] == data[p+length]:
                    length += 1
                if length > best_len:
                    best_len, best_off = length, p-j
                if best_len == maximum:
                    break
        if best_len < 2 and maximum >= 2:
            j = last_two.get(data[p:p+2], -1)
            if oldest_valid <= j < p:
                best_len, best_off = 2, p-j
        if best_len < 1 and maximum >= 1:
            j = last_one.get(data[p], -1)
            if oldest_valid <= j < p:
                best_len, best_off = 1, p-j
        output.append((best_off, best_len, data[p+best_len]))
        p += best_len + 1
    return output


def v5_lz77_deflate_compress(data: bytes) -> bytes:
    tokens = lz77_tokens(data, window=4096, lookahead=32)
    # Three independently canonical-Huffman-coded streams. A length of zero
    # designates a literal; a positive length is followed by a coded offset.
    lengths = [length for _, length, _ in tokens]
    offsets = [offset for offset, length, _ in tokens if length]
    literals = [literal for _, _, literal in tokens]
    length_codes = build_canonical(lengths)
    offset_codes = build_canonical(offsets)
    literal_codes = build_canonical(literals)
    writer = BitWriter()
    for offset, length, literal in tokens:
        writer.write(*length_codes[length])
        if length:
            writer.write(*offset_codes[offset])
        writer.write(*literal_codes[literal])
    header = (b'LZ05' + struct.pack('>II', len(data), len(tokens)) +
              serialize_lengths(length_codes, 1) +
              serialize_lengths(offset_codes, 2) +
              serialize_lengths(literal_codes, 1))
    return header + writer.finish()


def v5_lz77_deflate_decompress(packet: bytes) -> bytes:
    if len(packet) < 12 or packet[:4] != b'LZ05':
        raise ValueError('Invalid LZ77+Huffman packet')
    n, token_count = struct.unpack_from('>II', packet, 4)
    length_codes, cursor = parse_lengths(packet, 12, 1)
    offset_codes, cursor = parse_lengths(packet, cursor, 2)
    literal_codes, cursor = parse_lengths(packet, cursor, 1)
    get_length = decoder_for(length_codes)
    get_offset = decoder_for(offset_codes)
    get_literal = decoder_for(literal_codes)
    reader = BitReader(packet[cursor:])
    result = bytearray()
    for _ in range(token_count):
        length = get_length(reader)
        if length:
            offset = get_offset(reader)
            if not 1 <= length <= 32 or not 1 <= offset <= min(4096, len(result)):
                raise ValueError('Invalid LZ77 reference')
            for _ in range(length):
                result.append(result[-offset])  # overlap is intentionally legal
        result.append(get_literal(reader))
        if len(result) > n:
            raise ValueError('Output exceeds declared uncompressed size')
    if len(result) != n:
        raise ValueError('Incorrect LZ77 output size')
    return bytes(result)


CODECS = {
    'V1 Fixed-length': (v1_fixed_length_compress, v1_fixed_length_decompress),
    'V2 RLE': (v2_rle_compress, v2_rle_decompress),
    'V3 Huffman tree': (v3_huffman_tree_compress, v3_huffman_tree_decompress),
    'V4 Canonical Huffman': (v4_huffman_canonical_compress, v4_huffman_canonical_decompress),
    'V5 LZ77 + Canonical': (v5_lz77_deflate_compress, v5_lz77_deflate_decompress),
}


if __name__ == '__main__':
    samples = [b'', b'A', b'AAAAA', b'ABABABAB', b'ABRACADABRA ABRACADABRA', bytes(range(256)), b'\0' * 5000 + b'X' * 5000]
    for title, (enc, dec) in CODECS.items():
        for sample in samples:
            encoded = enc(sample)
            assert dec(encoded) == sample, (title, len(sample))
    print('All smoke tests passed:', len(CODECS)*len(samples))
