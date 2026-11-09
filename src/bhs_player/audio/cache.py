"""Disposable persistent metadata and decoded-PCM caches, never production data."""
from pathlib import Path
import hashlib
import json
import logging
import os
import tempfile
import threading
import numpy as np

ROOT = Path(os.environ.get("LOCALAPPDATA",Path.home()/".cache"))/"BHS Audio Production Player"/"audio-cache"
VERSION = 2
PCM_BUDGET = 512*1024*1024
_LOCK = threading.RLock()
log = logging.getLogger("bhs_player.audio")


def _path(kind, key, suffix):
    digest = hashlib.sha256(json.dumps([VERSION,kind,key],sort_keys=True).encode()).hexdigest()
    return ROOT/(digest+suffix)


def read_metadata(key, full=False):
    for kind in (("validated",) if full else ("validated","metadata")):
        try:
            data = json.loads(_path(kind,key,".json").read_text(encoding="utf-8"))
            if data.get("version")==VERSION and data.get("key")==list(key):
                result=data["result"]
                if result["duration"]>0 and result["sample_rate"]>0 and result["channels"] in (1,2):
                    return result
        except (OSError,ValueError,KeyError,TypeError):
            pass
    return None


def store_metadata(key, result, full=False):
    kind="validated" if full else "metadata"
    staged=None
    try:
        with _LOCK:
            ROOT.mkdir(parents=True,exist_ok=True)
            target=_path(kind,key,".json")
            with tempfile.NamedTemporaryFile(mode="w",encoding="utf-8",dir=ROOT,delete=False,suffix=".tmp") as out:
                staged=Path(out.name)
                json.dump(dict(version=VERSION,key=key,result=result),out)
            staged.replace(target)
            files=sorted(ROOT.glob("*.json"),key=lambda p:p.stat().st_mtime)
            for path in files[:-1024]:
                path.unlink(missing_ok=True)
    except OSError as exc:
        log.warning("AUDIO CACHE metadata write unavailable: %s",exc)
    finally:
        if staged is not None:
            try:staged.unlink(missing_ok=True)
            except OSError:pass


def load_pcm(key, limit):
    path=_path("pcm",key,".npy")
    mapped=None
    try:
        with _LOCK:
            mapped=np.load(path,mmap_mode="r",allow_pickle=False)
            if mapped.ndim!=2 or not len(mapped) or mapped.shape[1] not in (1,2) or mapped.dtype!=np.float32 or mapped.nbytes>limit:
                return None
            pcm=np.array(mapped,copy=True)
            if not np.isfinite(pcm).all():
                return None
            try:path.touch()
            except OSError:pass
            return pcm
    except (OSError,ValueError,EOFError,MemoryError):
        return None
    finally:
        if mapped is not None and getattr(mapped,"_mmap",None) is not None:
            mapped._mmap.close()


def store_pcm(key, pcm):
    staged=None
    try:
        with _LOCK:
            ROOT.mkdir(parents=True,exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=ROOT,delete=False,suffix=".tmp") as out:
                staged=Path(out.name)
                np.save(out,pcm,allow_pickle=False)
            staged.replace(_path("pcm",key,".npy"))
            files=sorted(ROOT.glob("*.npy"),key=lambda p:p.stat().st_mtime)
            total=sum(p.stat().st_size for p in files)
            for path in files:
                if total<=PCM_BUDGET:break
                size=path.stat().st_size
                path.unlink(missing_ok=True)
                total-=size
    except OSError as exc:
        log.warning("AUDIO CACHE PCM write unavailable: %s",exc)
    finally:
        if staged is not None:
            try:staged.unlink(missing_ok=True)
            except OSError:pass


def forget_metadata(key):
    for kind in ("validated","metadata"):
        try:_path(kind,key,".json").unlink(missing_ok=True)
        except OSError:pass
