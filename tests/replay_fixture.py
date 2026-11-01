"""A short recorded "game" for the replay tests, made from the shipped sample frame.

The sample is a real 1919x1079 capture with two spell pings in chat. Played as
it is from the first frame, those pings are history -- the app's priming pass
must not time them. Played after a blurred lead-in, they *appear* mid-recording,
which is what a ping looks like in a real VOD. One function makes both.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

import self_test


def sample_frame() -> np.ndarray:
    """The sample, trimmed to even dimensions (1918x1078).

    mp4v cannot store odd sizes and silently rounds them down, so trimming here
    keeps the fixture's frames exactly the frames that were written.
    """
    path = self_test.sample_dir() / self_test.IMAGE_NAME
    frame = cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_COLOR)
    height, width = frame.shape[:2]
    return np.ascontiguousarray(frame[:height - height % 2, :width - width % 2])


def make_fixture_video(path: Path, *, blurred_seconds: float = 2.0,
                       clear_seconds: float = 4.0, fps: int = 30,
                       still_from_start: bool = False) -> Path:
    """Write an mp4v video of the sample: blurred first, then clear."""
    frame = sample_frame()
    blurred = cv2.GaussianBlur(frame, (51, 51), 0)
    height, width = frame.shape[:2]
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps,
                             (width, height))
    if not writer.isOpened():
        raise RuntimeError(f"OpenCV cannot write {path}")
    lead = 0 if still_from_start else int(round(blurred_seconds * fps))
    clear = int(round(clear_seconds * fps)) + (
        int(round(blurred_seconds * fps)) if still_from_start else 0)
    for _ in range(lead):
        writer.write(blurred)
    for _ in range(clear):
        writer.write(frame)
    writer.release()
    return path
