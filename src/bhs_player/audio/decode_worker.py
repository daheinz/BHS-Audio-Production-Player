"""Disposable decoder process. Never imported for decoding in the GUI process."""
import json
import sys
import os
import faulthandler
faulthandler.enable()
if os.name == "nt":
    import ctypes
    ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002 | 0x8000)
from pathlib import Path



def open_source(path, request):
    import soundfile as sf
    try:
        return sf.SoundFile(path)
    except Exception as original:
        try:
            import av
        except ImportError:
            raise ValueError("Audio is unreadable or unsupported; AAC/M4A requires optional PyAV. " + str(original))
        converted = str(Path(request["result"]).with_name("converted.wav"))
        count = 0
        with av.open(path) as container:
            stream = next(s for s in container.streams if s.type == "audio")
            channels = stream.codec_context.channels
            sr = stream.codec_context.sample_rate
            if channels not in (1,2) or not sr:
                raise ValueError("Only readable mono/stereo audio is supported.")
            resampler = av.AudioResampler(format="fltp",layout="mono" if channels==1 else "stereo",rate=sr)
            with sf.SoundFile(converted,mode="w",samplerate=sr,channels=channels,subtype="FLOAT") as output:
                for frame in container.decode(stream):
                    for converted_frame in resampler.resample(frame):
                        data = converted_frame.to_ndarray().T
                        count += len(data)
                        if count*channels*4 > request["limit"]:
                            raise ValueError("Decoded audio exceeds the safety limit.")
                        output.write(data)
                for converted_frame in resampler.resample(None):
                    data = converted_frame.to_ndarray().T
                    count += len(data)
                    if count*channels*4 > request["limit"]:
                        raise ValueError("Decoded audio exceeds the safety limit.")
                    output.write(data)
        return sf.SoundFile(converted)

def main():
    request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    result_path = Path(request["result"])
    try:
        import numpy as np
        import soundfile as sf
        path, mode = request["path"], request["mode"]
        limit = request["limit"]
        with open_source(path, request) as sound:
            frames, sr, channels = sound.frames, sound.samplerate, sound.channels
            if frames <= 0 or sr <= 0 or channels not in (1, 2):
                raise ValueError("Audio needs positive duration and one or two channels.")
            result = {"duration": frames/sr, "sample_rate": sr, "channels": channels, "format": sound.format}
            if mode != "probe":
                start = int(request.get("start", 0)*sr) if mode == "decode" else 0
                end_seconds = request.get("end") if mode == "decode" else None
                end = min(frames, int(end_seconds*sr)) if end_seconds else frames
                if start < 0 or start >= end:
                    raise ValueError("Start must precede End within the recording.")
                target = request.get("rate") or sr
                expected = int((end-start)*target/sr)*channels*4
                if expected > limit:
                    raise ValueError("Decoded audio exceeds the 128 MiB safety limit; use a shorter clip or a clean, shorter export.")
                sound.seek(start)
                remaining, count = end-start, 0
                chunks = []
                buckets = request.get("buckets", 1600)
                bucket_size = max(1, int(np.ceil(frames/buckets)))
                if mode == "waveform":
                    low = np.zeros((int(np.ceil(frames/bucket_size)),channels),dtype=np.float32)
                    high = low.copy()
                while remaining:
                    block = sound.read(min(65536, remaining), dtype="float32", always_2d=True)
                    if not len(block):
                        raise ValueError("Decoder ended before the declared audio length; file may be truncated.")
                    if not np.isfinite(block).all():
                        raise ValueError("Decoder returned invalid audio samples.")
                    if mode == "decode":
                        chunks.append(block)
                    elif mode == "waveform":
                        indices = (count + np.arange(len(block)))//bucket_size
                        for channel in range(channels):
                            np.minimum.at(low[:,channel],indices,block[:,channel])
                            np.maximum.at(high[:,channel],indices,block[:,channel])
                    count += len(block)
                    remaining -= len(block)
                if mode == "decode":
                    pcm = np.concatenate(chunks, axis=0)
                    chunks.clear()
                    if sr != target:
                        length = max(1, int(round(len(pcm)*target/sr)))
                        converted = np.empty((length,channels),dtype=np.float32)
                        for offset in range(0,length,65536):
                            positions = np.arange(offset,min(length,offset+65536),dtype=np.float64)*(sr/target)
                            left = np.minimum(positions.astype(np.int64),len(pcm)-1)
                            right = np.minimum(left+1,len(pcm)-1)
                            fraction = np.clip(positions-left,0,1).astype(np.float32)[:,None]
                            converted[offset:offset+len(left)] = pcm[left]*(1-fraction)+pcm[right]*fraction
                        pcm = converted
                    if pcm.nbytes > limit:
                        raise ValueError("Decoded audio exceeds the safety limit.")
                    np.save(request["output"],pcm,allow_pickle=False)
                    result["sample_rate"] = target
                elif mode == "waveform":
                    np.savez(request["output"],minimum=low,maximum=high)
        result_path.write_text(json.dumps(result),encoding="utf-8")
    except BaseException as exc:
        result_path.write_text(json.dumps({"error": str(exc) or type(exc).__name__}),encoding="utf-8")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
