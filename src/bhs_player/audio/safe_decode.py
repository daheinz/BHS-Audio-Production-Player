"""Bounded, killable decoder isolation shared by playback, imports and waveforms."""
from pathlib import Path
from collections import OrderedDict
import json
import hashlib
import logging
import os
import subprocess
import sys
import tempfile
import threading
import time
import numpy as np
from . import cache as disk_cache

log = logging.getLogger("bhs_player.audio")
DECODE_TIMEOUT = 20.0
PROBE_TIMEOUT = 5.0
DECODE_LIMIT = 128*1024*1024
_CACHE = OrderedDict()
_SUSPECT = {}
_LOCK = threading.Lock()
# Limit concurrent native decoders so cue preloading cannot create a process storm.
_SLOTS = threading.BoundedSemaphore(2)


def fingerprint(path):
    path = Path(path).resolve()
    stat = path.stat()
    return str(path), stat.st_size, stat.st_mtime_ns


def inspect_audio(path, full=False, force=False, analyze_peaks=False):
    full = full or analyze_peaks
    key = fingerprint(path)
    if force:
        with _LOCK:
            _CACHE.pop((key,"validate"),None)
            _CACHE.pop((key,"probe"),None)
            _SUSPECT.pop(key,None)
        disk_cache.forget_metadata(key)
    cache_key = (key, "validate" if full else "probe")
    with _LOCK:
        cached = _CACHE.get(cache_key) or (None if full else _CACHE.get((key,"validate")))
    if cached and (not analyze_peaks or "sample_peak" in cached):
        return dict(cached)
    if not force:
        cached = disk_cache.read_metadata(key, full)
        if cached and (not analyze_peaks or "sample_peak" in cached):
            with _LOCK:_CACHE[cache_key]=cached
            return dict(cached)
    result, pcm = _run(path, "validate" if full else "probe",rate=44100 if full else None)
    if fingerprint(path) != key:
        raise RuntimeError("Audio changed while being checked; try again.")
    with _LOCK:
        _CACHE[cache_key] = result
        while len(_CACHE) > 128:
            _CACHE.popitem(last=False)
    disk_cache.store_metadata(key,result,full)
    if full and pcm is not None:
        disk_cache.store_pcm(_pcm_key(key,result,0,None,44100),pcm)
    return dict(result)



def validated_audio(path):
    """GUI commit must never start a fresh check after an async result."""
    key = fingerprint(path)
    with _LOCK:
        result = _CACHE.get((key,"validate"))
    if result is None:
        result = disk_cache.read_metadata(key,full=True)
    if result is None:
        log.error("AUDIO SAFETY REJECT mode=assignment file=%r reason=validation expired or source changed",str(path))
        raise RuntimeError("Audio changed or its validation expired; select the file again to recheck it.")
    return dict(result)


def remember_validated_copy(path, result):
    """Only called after a validated source's copy has been hash-verified."""
    key = fingerprint(path)
    with _LOCK:
        _CACHE[(key,"validate")] = dict(result)
        while len(_CACHE) > 128:
            _CACHE.popitem(last=False)
    disk_cache.store_metadata(key,result,full=True)

def _pcm_key(source,metadata,start,end,rate):
    source_id=metadata.get('source_sha256') or source
    if end is not None and metadata.get('duration') and abs(end-metadata['duration'])<1/metadata.get('sample_rate',44100):
        end=None
    return source_id,float(start or 0),float(end) if end is not None else None,rate


def decode_audio(path, cue, rate):
    source=fingerprint(path)
    with _LOCK:reason=_SUSPECT.get(source)
    if reason:
        raise RuntimeError("Suspect audio blocked: "+reason+". Replace or re-export the file.")
    metadata=disk_cache.read_metadata(source) or {}
    # Many productions give identical audio different filenames. Hash small
    # source assets once in preparation so they share proven decoded data;
    # persist that identity so future arming does not repeat the hash.
    if not metadata.get('source_sha256') and source[1]<=64*1024*1024:
        with open(path,'rb') as stream:
            digest=hashlib.file_digest(stream,'sha256').hexdigest()
        if fingerprint(path)!=source:
            raise RuntimeError("Audio changed during preparation; try again.")
        metadata=dict(metadata,source_sha256=digest)
        if metadata.get('duration'):
            disk_cache.store_metadata(source,metadata)
    key=_pcm_key(source,metadata,cue.start_position,cue.end_position,rate)
    cached=disk_cache.load_pcm(key,DECODE_LIMIT)
    if cached is not None and fingerprint(path)==source:
        log.info("AUDIO PCM CACHE HIT file=%r bytes=%s",str(path),cached.nbytes)
        return cached,rate or inspect_audio(path)["sample_rate"]
    result, pcm = _run(path,"decode",start=cue.start_position or 0,
                       end=cue.end_position,rate=rate)
    if fingerprint(path)==source:
        metadata=dict(result,sample_rate=result.get('source_sample_rate',result['sample_rate']))
        disk_cache.store_metadata(source,metadata)
        disk_cache.store_pcm(_pcm_key(source,metadata,cue.start_position,cue.end_position,rate),pcm)
    return pcm, result["sample_rate"]


def waveform_audio(path, buckets=1600):
    result, data = _run(path,"waveform",buckets=buckets)
    return result["duration"], data


def _run(path, mode, timeout=None, **extra):
    key = fingerprint(path)
    with _LOCK:
        reason = _SUSPECT.get(key)
    if reason:
        raise RuntimeError("Suspect audio blocked: " + reason + ". Replace or re-export the file.")
    timeout = timeout or (PROBE_TIMEOUT if mode == "probe" else DECODE_TIMEOUT)
    if not _SLOTS.acquire(timeout=timeout):
        log.error("AUDIO SAFETY REJECT mode=%s file=%r reason=decoder workers busy",mode,str(path))
        raise RuntimeError("Audio preparation busy; try again after the current checks finish.")
    try:
        return _execute(path,mode,key,timeout,extra)
    finally:
        _SLOTS.release()


def _execute(path, mode, key, timeout, extra):
    process = None
    job = None
    suspect = False
    try:
        with tempfile.TemporaryDirectory(prefix="bhs-audio-") as temporary:
            root = Path(temporary)
            request = dict(path=str(Path(path).resolve()), mode=mode, limit=DECODE_LIMIT,
                           result=str(root/"result.json"),output=str(root/("audio.npz" if mode=="waveform" else "audio.npy")),**extra)
            request_file = root/"request.json"
            request_file.write_text(json.dumps(request),encoding="utf-8")
            flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            # Decoder work is block I/O and elementwise math, not BLAS. Large
            # default BLAS pools can consume almost the entire Windows job
            # memory budget before any audio is decoded.
            environment = os.environ.copy()
            for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "BLIS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
                environment[name] = "1"
            process = subprocess.Popen([sys.executable,str(Path(__file__).with_name("decode_worker.py")),str(request_file)],
                                       stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,
                                       creationflags=flags, env=environment)
            from .process_limits import attach_decoder_job
            job = attach_decoder_job(process)
            errors = bytearray()
            warned = threading.Event()
            def drain():
                while True:
                    data = process.stderr.read(1)
                    if not data:
                        break
                    if len(errors) < 8192:
                        errors.extend(data)
                    warned.set()
            reader = threading.Thread(target=drain,daemon=True)
            reader.start()
            deadline = time.monotonic()+timeout
            while process.poll() is None:
                if warned.wait(.02):
                    suspect = True
                    process.kill()
                    break
                if time.monotonic() >= deadline:
                    suspect = True
                    process.kill()
                    break
            process.wait()
            reader.join(timeout=2)
            process.stderr.close()
            if suspect:
                if errors:
                    raise RuntimeError("Decoder reported errors: " + errors.decode("utf-8",errors="replace")[:1800])
                raise RuntimeError(f"Decoder timed out after {timeout:g} seconds.")
            if errors:
                suspect = True
                raise RuntimeError("Decoder reported errors: " + errors.decode("utf-8",errors="replace")[:1800])
            result_file = Path(request["result"])
            if not result_file.exists():
                suspect = True
                raise RuntimeError(f"Decoder process exited unexpectedly (code {process.returncode}).")
            result = json.loads(result_file.read_text(encoding="utf-8"))
            if result.get("error"):
                raise RuntimeError(result["error"])
            if process.returncode:
                suspect = True
                raise RuntimeError(f"Decoder failed (code {process.returncode}).")
            if fingerprint(path) != key:
                raise RuntimeError("Audio changed during decoding; try again.")
            if result.get("diagnostic_warning"):
                log.warning("AUDIO LENGTH ADJUSTMENT mode=%s file=%r detail=%s",
                            mode, str(path), result["diagnostic_warning"])
            output = None
            if mode in ("decode","validate"):
                output = np.load(request["output"],allow_pickle=False)
                if output.ndim != 2 or not len(output) or output.shape[1] not in (1,2) or output.nbytes > DECODE_LIMIT or not np.isfinite(output).all():
                    raise RuntimeError("Decoded audio failed safety checks.")
            elif mode == "waveform":
                with np.load(request["output"],allow_pickle=False) as data:
                    output = (data["minimum"].copy(), data["maximum"].copy())
            return result, output
    except Exception as exc:
        if suspect:
            with _LOCK:
                _SUSPECT[key] = str(exc)
        log.error("AUDIO SAFETY REJECT mode=%s file=%r reason=%s",mode,str(path),exc)
        raise
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait()
        from .process_limits import close_decoder_job
        close_decoder_job(job)
