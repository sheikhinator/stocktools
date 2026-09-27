"""API keys are stored encrypted with Windows DPAPI (only this Windows user on this PC can read them).
On other systems (development) they are only obfuscated."""

from __future__ import annotations

import base64
import sys


def _dpapi(data: bytes, protect: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    buf = ctypes.create_string_buffer(data, len(data))
    src = BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    dst = BLOB()
    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    if not fn(ctypes.byref(src), None, None, None, None, 0x01, ctypes.byref(dst)):   # CRYPTPROTECT_UI_FORBIDDEN
        raise OSError("DPAPI failed")
    try:
        return ctypes.string_at(dst.pbData, dst.cbData)
    finally:
        kernel32.LocalFree(dst.pbData)


def protect(text: str) -> str:
    if not text:
        return ""
    raw = text.encode("utf-8")
    if sys.platform == "win32":
        try:
            return "dpapi:" + base64.b64encode(_dpapi(raw, True)).decode()
        except Exception:
            pass
    return "b64:" + base64.b64encode(raw[::-1]).decode()


def unprotect(blob: str) -> str:
    if not blob:
        return ""
    try:
        if blob.startswith("dpapi:"):
            return _dpapi(base64.b64decode(blob[6:]), False).decode("utf-8")
        if blob.startswith("b64:"):
            return base64.b64decode(blob[4:])[::-1].decode("utf-8")
    except Exception:
        return ""
    return blob


def mask(key: str) -> str:
    return "" if not key else (key[:4] + "…" + key[-4:] if len(key) > 10 else "…")
