#!/usr/bin/env python3
"""Convert a G.711 A-law 8 kHz mono WAV into a real RTP pcap for SIPp.

SIPp's play_pcap_audio requires an actual libpcap capture containing RTP
packets — a renamed WAV does not work. Stdlib only: builds
Ethernet/IPv4/UDP/RTP frames with payload type 8 (PCMA), 20 ms per packet
(160 A-law bytes @ 8 kHz). IP/port placeholders are rewritten by SIPp at
replay time.

Usage: wav_to_pcap.py input.wav output.pcap
"""
import struct
import sys

SAMPLES_PER_PACKET = 160  # 20 ms @ 8 kHz
PT_PCMA = 8
SSRC = 0x53505031  # 'SPP1'


def read_wav_data(path: str) -> bytes:
    """Extract the raw payload of the RIFF 'data' chunk (A-law bytes)."""
    with open(path, "rb") as f:
        riff = f.read()
    if riff[:4] != b"RIFF" or riff[8:12] != b"WAVE":
        raise ValueError(f"{path}: not a RIFF/WAVE file")
    pos = 12
    while pos + 8 <= len(riff):
        chunk_id = riff[pos:pos + 4]
        size = struct.unpack_from("<I", riff, pos + 4)[0]
        if chunk_id == b"data":
            return riff[pos + 8:pos + 8 + size]
        pos += 8 + size + (size & 1)  # chunks are 2-byte aligned
    raise ValueError(f"{path}: no 'data' chunk found")


def ip_checksum(header: bytes) -> int:
    if len(header) % 2:
        header += b"\x00"
    s = sum(struct.unpack(f">{len(header) // 2}H", header))
    s = (s >> 16) + (s & 0xFFFF)
    s += s >> 16
    return ~s & 0xFFFF


def build_frame(payload: bytes, seq: int, timestamp: int) -> bytes:
    rtp = struct.pack(">BBHII", 0x80, PT_PCMA, seq & 0xFFFF, timestamp, SSRC)
    udp_len = 8 + len(rtp) + len(payload)
    src_ip = dst_ip = b"\x7f\x00\x00\x01"  # 127.0.0.1 placeholder
    ip = struct.pack(
        ">BBHHHBBH4s4s", 0x45, 0, 20 + udp_len, seq & 0xFFFF, 0, 64, 17, 0,
        src_ip, dst_ip,
    )
    ip = ip[:10] + struct.pack(">H", ip_checksum(ip)) + ip[12:]
    udp = struct.pack(">HHHH", 40000, 50000, udp_len, 0)  # no UDP checksum (IPv4)
    eth = b"\x02\x00\x00\x00\x00\x02" + b"\x02\x00\x00\x00\x00\x01" + b"\x08\x00"
    return eth + ip + udp + rtp + payload


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    data = read_wav_data(sys.argv[1])
    with open(sys.argv[2], "wb") as f:
        # pcap global header: little-endian, linktype Ethernet (1)
        f.write(struct.pack("<IHHIIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1))
        usec = 0
        for seq, off in enumerate(range(0, len(data) - SAMPLES_PER_PACKET + 1, SAMPLES_PER_PACKET)):
            frame = build_frame(data[off:off + SAMPLES_PER_PACKET], seq, seq * SAMPLES_PER_PACKET)
            f.write(struct.pack("<IIII", usec // 1_000_000, usec % 1_000_000, len(frame), len(frame)))
            f.write(frame)
            usec += 20_000


if __name__ == "__main__":
    main()
