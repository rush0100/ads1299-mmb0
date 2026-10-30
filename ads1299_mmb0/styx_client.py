"""Minimal Inferno/TI Styx client used by MMB0 firmware.

Matches TI cstyx Client: Tattach without Tversion, tag=1, uname/aname
\"nobody\". Tread/Twrite use 32-bit offset + 32-bit zero pad (looks like
a 64-bit offset with high half zero on the wire).
"""

from __future__ import annotations

import struct
from typing import Iterable

from .styx_usb import StyxUSB

Tattach, Rattach = 104, 105
Rerror = 107
Twalk, Rwalk = 110, 111
Topen, Ropen = 112, 113
Tread, Rread = 116, 117
Twrite, Rwrite = 118, 119
Tclunk, Rclunk = 120, 121

OREAD, OWRITE, ORDWR = 0, 1, 2
# TI cstyx Fid::open() ORs Unix mode bits (0444/0222). Wire mode is u8, so
# low byte is 0x24 / 0x92 / 0xB6. Bits 0–1 still match 9P OREAD / ORDWR.
TI_OREAD = 0o444 & 0xFF  # 0x24
TI_OWRITE = 0o222 & 0xFF  # 0x92 — LabVIEW write opens; not plain OWRITE=1
TI_ORDWR = (0o444 | 0o222) & 0xFF  # 0xB6 — /ads1299evm/data (LabVIEW read+write_path)
NOFID = 0xFFFFFFFF
ROOT_FID, CWD_FID, FIRST_FID = 1, 2, 10


class StyxError(RuntimeError):
    pass


def _pstring(s: str) -> bytes:
    b = s.encode("utf-8")
    return struct.pack("<H", len(b)) + b


def _gstring(buf: memoryview, off: int) -> tuple[str, int]:
    (n,) = struct.unpack_from("<H", buf, off)
    off += 2
    s = bytes(buf[off : off + n]).decode("utf-8", errors="replace")
    return s, off + n


def _hdr(mtype: int, tag: int) -> bytes:
    return struct.pack("<BH", mtype, tag)


class StyxClient:
    def __init__(self, transport: StyxUSB) -> None:
        self.t = transport
        self._next_fid = FIRST_FID
        self._tag = 1
        self._rpc(self._mk_attach(ROOT_FID))
        self._rpc(self._mk_walk(ROOT_FID, CWD_FID, []))

    def close(self) -> None:
        self.t.close()

    def __enter__(self) -> StyxClient:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _new_fid(self) -> int:
        fid = self._next_fid
        self._next_fid += 1
        if self._next_fid > 32760:
            self._next_fid = FIRST_FID
        return fid

    def _rpc(self, body: bytes) -> bytes:
        msg = struct.pack("<I", 4 + len(body)) + body
        self.t.write(msg)
        hdr = self.t.read(4)
        (size,) = struct.unpack("<I", hdr)
        if size < 7:
            raise StyxError(f"bad message size {size}")
        rest = self.t.read(size - 4)
        self.t.flush()
        data = hdr + rest
        mtype = data[4]
        if mtype == Rerror:
            ename, _ = _gstring(memoryview(data), 7)
            raise StyxError(ename)
        return data

    def _mk_attach(self, fid: int) -> bytes:
        return (
            _hdr(Tattach, self._tag)
            + struct.pack("<II", fid, NOFID)
            + _pstring("nobody")
            + _pstring("nobody")
        )

    def _mk_walk(self, fid: int, newfid: int, names: Iterable[str]) -> bytes:
        names = list(names)
        body = _hdr(Twalk, self._tag) + struct.pack("<IIH", fid, newfid, len(names))
        for n in names:
            body += _pstring(n)
        return body

    def _mk_open(self, fid: int, mode: int) -> bytes:
        return _hdr(Topen, self._tag) + struct.pack("<IB", fid, mode)

    def _mk_clunk(self, fid: int) -> bytes:
        return _hdr(Tclunk, self._tag) + struct.pack("<I", fid)

    def _mk_read(self, fid: int, offset: int, count: int) -> bytes:
        # offset[4] + high[4]=0 + count[4]  (TI styxmsg.cc)
        return _hdr(Tread, self._tag) + struct.pack("<IIII", fid, offset, 0, count)

    def _mk_write(self, fid: int, offset: int, data: bytes) -> bytes:
        return (
            _hdr(Twrite, self._tag)
            + struct.pack("<IIII", fid, offset, 0, len(data))
            + data
        )

    def _split_path(self, path: str) -> tuple[int, list[str]]:
        path = path.replace("\\", "/")
        if path.startswith("/"):
            return ROOT_FID, [p for p in path.split("/") if p]
        return CWD_FID, [p for p in path.split("/") if p]

    def walk(self, path: str) -> int:
        base, parts = self._split_path(path)
        fid = self._new_fid()
        self._rpc(self._mk_walk(base, fid, parts))
        return fid

    def open_fid(self, path: str, mode: int = TI_OREAD) -> int:
        """Walk + open; caller owns the FID (must clunk). Matches cstyx File ctor."""
        fid = self.walk(path)
        try:
            self._rpc(self._mk_open(fid, mode & 0xFF))
        except Exception:
            try:
                self._rpc(self._mk_clunk(fid))
            except StyxError:
                pass
            raise
        return fid

    def read_fid(self, fid: int, limit: int, *, offset: int = 0, chunk: int = 1024) -> bytes:
        """Sequential Tread on an open FID (cstyx File::readAll, ≤1024 B/chunk)."""
        chunks: list[bytes] = []
        off = int(offset)
        while off < limit:
            want = min(chunk, limit - off)
            resp = self._rpc(self._mk_read(fid, off, want))
            (count,) = struct.unpack_from("<I", resp, 7)
            if count == 0:
                break
            chunks.append(resp[11 : 11 + count])
            off += count
            if count < want:
                break
        return b"".join(chunks)

    def write_fid(self, fid: int, data: bytes | str, *, offset: int = 0) -> int:
        if isinstance(data, str):
            data = data.encode("ascii", errors="strict")
        resp = self._rpc(self._mk_write(fid, offset, data))
        (count,) = struct.unpack_from("<I", resp, 7)
        return count

    def clunk(self, fid: int) -> None:
        try:
            self._rpc(self._mk_clunk(fid))
        except StyxError:
            pass

    def read_all(self, path: str, limit: int = 32767) -> bytes:
        fid = self.open_fid(path, TI_OREAD)
        try:
            return self.read_fid(fid, limit)
        finally:
            self.clunk(fid)

    def write_all(self, path: str, data: bytes | str) -> int:
        if isinstance(data, str):
            data = data.encode("ascii", errors="strict")
        # Match TI Fid::open(write): mode 0222 → wire 0x92 (ORDWR in low 2 bits).
        fid = self.open_fid(path, TI_OWRITE)
        try:
            resp = self._rpc(self._mk_write(fid, 0, data))
            (count,) = struct.unpack_from("<I", resp, 7)
            return count
        finally:
            self.clunk(fid)

    def read_text(self, path: str) -> str:
        return self.read_all(path).decode("ascii", errors="replace").strip()

    def write_text(self, path: str, text: str) -> int:
        return self.write_all(path, text)
