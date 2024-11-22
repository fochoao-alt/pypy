from _gdbm_cffi import ffi, lib    # generated by _gdbm_build.py
import sys, os, threading
_lock = threading.Lock()

class error(OSError):
    pass

def _checkstr(key):
    if isinstance(key, str):
        key = key.encode()
    if not isinstance(key, bytes):
        raise TypeError("gdbm mappings have string indices only")
    return key

def _fromstr(key):
    if isinstance(key, str):
        key = key.encode(sys.getdefaultencoding())
    elif not isinstance(key, bytes):
        msg = "gdbm mappings have bytes or string indices only, not {!r}"
        raise TypeError(msg.format(type(key).__name__))
    return {'dptr': ffi.new("char[]", key), 'dsize': len(key)}

class gdbm(object):
    __ll_dbm = None

    # All public methods need to acquire the lock; all private methods
    # assume the lock is already held.  Thus public methods cannot call
    # other public methods.

    def __init__(self, filename, iflags, mode):
        with _lock:
            res = lib.gdbm_open(filename, 0, iflags, mode, ffi.NULL)
            self.__size = -1
            if not res:
                self.__raise_from_errno(filename=filename)
            self.__ll_dbm = res

    def close(self):
        with _lock:
            if self.__ll_dbm:
                lib.pygdbm_close(self.__ll_dbm)
                self.__ll_dbm = None

    def __raise_from_errno(self, filename=None):
        if ffi.errno:
            if filename:
                if not isinstance(filename, str):
                    filename = filename.decode()
                raise error(ffi.errno, os.strerror(ffi.errno), filename)
            else:
                raise error(ffi.errno, )
        raise error(lib.gdbm_errno, lib.gdbm_strerror(lib.gdbm_errno))

    def __len__(self):
        with _lock:
            if self.__size < 0:
                self.__size = len(self.__keys())
            return self.__size

    def __setitem__(self, key, value):
        with _lock:
            self.__check_closed()
            self.__size = -1
            r = lib.gdbm_store(self.__ll_dbm, _fromstr(key), _fromstr(value),
                               lib.GDBM_REPLACE)
            if r < 0:
                self.__raise_from_errno()

    def __delitem__(self, key):
        with _lock:
            self.__check_closed()
            self.__size = -1
            res = lib.gdbm_delete(self.__ll_dbm, _fromstr(key))
            if res <0:
                if lib.gdbm_errno == lib.GDBM_ITEM_NOT_FOUND:
                    raise KeyError(key)
                self.__raise_from_errno()

    def __contains__(self, key):
        with _lock:
            self.__check_closed()
            key = _checkstr(key)
            return lib.pygdbm_exists(self.__ll_dbm, key, len(key))

    def get(self, key, default=None):
        with _lock:
            self.__check_closed()
            key = _checkstr(key)
            drec = lib.pygdbm_fetch(self.__ll_dbm, key, len(key))
            if not drec.dptr:
                return default
            res = bytes(ffi.buffer(drec.dptr, drec.dsize))
            lib.free(drec.dptr)
            return res

    def __getitem__(self, key):
        value = self.get(key)
        if value is None:
            raise KeyError(key)
        return value

    def __keys(self):
        self.__check_closed()
        l = []
        key = lib.gdbm_firstkey(self.__ll_dbm)
        while key.dptr:
            l.append(bytes(ffi.buffer(key.dptr, key.dsize)))
            nextkey = lib.gdbm_nextkey(self.__ll_dbm, key)
            lib.free(key.dptr)
            key = nextkey
        return l

    def keys(self):
        with _lock:
            return self.__keys()

    def firstkey(self):
        with _lock:
            self.__check_closed()
            key = lib.gdbm_firstkey(self.__ll_dbm)
            if key.dptr:
                res = bytes(ffi.buffer(key.dptr, key.dsize))
                lib.free(key.dptr)
                return res

    def nextkey(self, key):
        with _lock:
            self.__check_closed()
            key = lib.gdbm_nextkey(self.__ll_dbm, _fromstr(key))
            if key.dptr:
                res = bytes(ffi.buffer(key.dptr, key.dsize))
                lib.free(key.dptr)
                return res

    def reorganize(self):
        with _lock:
            self.__check_closed()
            if lib.gdbm_reorganize(self.__ll_dbm) < 0:
                self.__raise_from_errno()

    def __check_closed(self):
        if not self.__ll_dbm:
            raise error("GDBM object has already been closed")

    __del__ = close

    def sync(self):
        with _lock:
            self.__check_closed()
            lib.gdbm_sync(self.__ll_dbm)

    def setdefault(self, key, default=None):
        value = self.get(key)
        if value is not None:
            return value
        self[key] = default
        return default

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()


def open(filename, flags='r', mode=0o666):
    filename = os.fsencode(filename)

    if flags[0] == 'r':
        iflags = lib.GDBM_READER
    elif flags[0] == 'w':
        iflags = lib.GDBM_WRITER
    elif flags[0] == 'c':
        iflags = lib.GDBM_WRCREAT
    elif flags[0] == 'n':
        iflags = lib.GDBM_NEWDB
    else:
        raise error(0, "First flag must be one of 'r', 'w', 'c' or 'n'")
    for flag in flags[1:]:
        if flag == 'f':
            iflags |= lib.GDBM_FAST
        elif flag == 's':
            iflags |= lib.GDBM_SYNC
        elif flag == 'u':
            iflags |= lib.GDBM_NOLOCK
        else:
            raise error(0, "Flag '%s' not supported" % flag)
    return gdbm(filename, iflags, mode)

open_flags = "rwcnfsu"
