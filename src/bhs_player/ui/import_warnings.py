"""Advisory peak warnings from silent import analysis; never reject audio."""
import logging
import math
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox


def peak_warnings(metadata, cue, profile):
    peak = metadata.get("sample_peak")
    if peak is None or peak <= 0:
        return []
    db = 20 * math.log10(peak)
    warnings = []
    if peak >= 0.9999:
        warnings.append(f"Source reaches full scale ({db:+.1f} dBFS); possible clipping. "
                        "A full-scale peak alone does not prove distortion.")
    elif peak >= 10 ** (-1 / 20):
        warnings.append(f"Source has little headroom ({db:+.1f} dBFS peak).")
    for bus in profile.buses:
        if bus.id in cue.bus_ids and peak * cue.volume * bus.level > 1:
            output_db = 20 * math.log10(peak * cue.volume * bus.level)
            warnings.append(f"Cue level and {bus.name} bus level could exceed full scale "
                            f"({output_db:+.1f} dBFS peak). Reduce the cue or bus level.")
    return warnings


def show_import_warnings(parent, metadata, cue, profile):
    warnings = peak_warnings(metadata, cue, profile)
    if not warnings:
        return ""
    text = "\n\n".join(warnings)
    logging.getLogger("bhs_player.audio").warning("AUDIO IMPORT PEAK WARNING cue=%s detail=%s", cue.identifier, text)
    box = QMessageBox(QMessageBox.Warning, "Audio imported - level warning", text, QMessageBox.Ok, parent)
    box.setInformativeText("Audio was imported. Analysis uses the whole source and current cue/bus levels; "
                           "trim/fades may lower peaks. Overlapping sounds can clip even if this file passes. "
                           "Use TEST and Audio Health to check live playback.")
    box.setAttribute(Qt.WA_DeleteOnClose)
    boxes = getattr(parent, "_audio_warning_boxes", None)
    if boxes is None:
        parent._audio_warning_boxes = boxes = []
    boxes.append(box)
    box.finished.connect(lambda _: boxes.remove(box) if box in boxes else None)
    box.open()
    return text
