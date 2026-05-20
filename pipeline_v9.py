"""
Pipeline v9.0 — DaVinci Resolve Emulation

The secret: TikTok doesn't just hash pixels — it fingerprints the H.264 
BITSTREAM STRUCTURE (B-frame placement, macroblock decisions, quantization 
distribution). DaVinci Resolve bypasses detection by simply re-encoding with 
completely different encoder decisions, even with zero visual changes.

This pipeline replicates DaVinci Resolve's exact export settings:
  - H.264 High Profile
  - Adaptive B-frames (b-adapt=2)
  - AQ Strength ~1.0 (DaVinci "8" maps to ~1.0 in x264)
  - Lookahead 16 frames
  - Frame reordering ON
  - Variable Bitrate, High Quality tuning
  - Automatic keyframe placement

PLUS our minimal visual tweaks for extra safety.
"""
import os, json, uuid, random, subprocess, time

PIPELINE_VERSION = "9.0-davinci-emulation"


def _probe(path):
    r = subprocess.run(["ffprobe", "-v", "quiet", "-print_format", "json",
                        "-show_streams", "-show_format", path],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return {"w": 1080, "h": 1920, "audio": False, "fps": 30, "dur": 10,
                "a_rate": 44100}
    d = json.loads(r.stdout)
    w, h, audio, fps, a_rate = 1080, 1920, False, 30, 44100
    for s in d.get("streams", []):
        if s.get("codec_type") == "video":
            w, h = int(s.get("width", 1080)), int(s.get("height", 1920))
            try:
                n, dn = s.get("r_frame_rate", "30/1").split("/")
                fps = round(int(n) / int(dn), 2)
            except: pass
        elif s.get("codec_type") == "audio":
            audio = True
            a_rate = int(s.get("sample_rate", 44100))
    dur = float(d.get("format", {}).get("duration", 10))
    return {"w": w, "h": h, "audio": audio, "fps": fps, "dur": dur,
            "a_rate": a_rate}


def process_video(input_path, output_path, use_nvenc=True):
    info = _probe(input_path)
    w, h, fps = info["w"], info["h"], info["fps"]
    has_audio, duration = info["audio"], info["dur"]
    a_rate = info["a_rate"]
    print(f"[V9] {w}x{h} @{fps}fps audio={has_audio} dur={duration:.1f}s")

    # ── Minimal visual tweaks (subtle, won't darken) ──
    zoom = round(random.uniform(1.01, 1.03), 3)
    dx = random.randint(-2, 2)
    dy = random.randint(-2, 2)
    speed = round(random.uniform(1.005, 1.02), 3)
    contrast = round(random.uniform(1.00, 1.03), 3)
    saturation = round(random.uniform(1.00, 1.04), 3)
    hue_shift = random.choice([-2, -1, 0, 1, 2])

    # Trim: shave a tiny bit from start/end (shifts keyframes)
    trim_s = round(random.uniform(0.04, 0.15), 3)
    trim_e = round(random.uniform(0.04, 0.15), 3)
    trimmed_dur = round(duration - trim_s - trim_e, 3)
    if trimmed_dur < 1.0:
        trim_s = trim_e = 0
        trimmed_dur = duration

    # Audio pitch (very subtle)
    pitch_rate = round(a_rate * random.uniform(0.995, 1.005))

    p = {
        "pipeline_version": PIPELINE_VERSION,
        "zoom": zoom, "speed": speed, "contrast": contrast,
        "saturation": saturation, "hue": hue_shift,
        "trim_start": trim_s, "trim_end": trim_e,
        "pitch_rate": pitch_rate,
        "original_size": f"{w}x{h}", "fps": fps,
    }

    # ── Video filter (minimal) ──
    crop_w = int(w / zoom)
    crop_h = int(h / zoom)
    crop_x = max(0, min(int((w - crop_w) / 2 + dx), w - crop_w))
    crop_y = max(0, min(int((h - crop_h) / 2 + dy), h - crop_h))

    vf = [
        f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y}",
        f"scale={w}:{h}",
        f"eq=contrast={contrast}:saturation={saturation}",
    ]
    if hue_shift != 0:
        vf.append(f"hue=h={hue_shift}")
    vf.append(f"setpts=PTS/{speed}")

    vf_str = ",".join(vf)

    # ── Audio filter (minimal) ──
    af_str = ""
    if has_audio:
        af_parts = [
            f"atempo={speed:.3f}",
            f"asetrate={pitch_rate}",
            f"aresample={a_rate}",
        ]
        af_str = ",".join(af_parts)

    # ── Build FFmpeg command — DaVinci Resolve emulation ──
    title = f"clip-{uuid.uuid4().hex[:8]}"
    cmd = ["ffmpeg", "-y"]

    # Input with trim
    if trim_s > 0:
        cmd.extend(["-ss", str(trim_s)])
    cmd.extend(["-i", input_path])
    if trimmed_dur > 1 and trim_e > 0:
        cmd.extend(["-t", str(trimmed_dur)])

    # Video filter
    cmd.extend(["-vf", vf_str])

    # Audio filter
    if has_audio and af_str:
        cmd.extend(["-af", af_str])

    # ═══════════════════════════════════════════════════════
    # DaVinci Resolve H.264 Encoder Settings (EXACT MATCH)
    # ═══════════════════════════════════════════════════════
    #
    # These settings replicate what DaVinci does internally.
    # The KEY is that x264 with these params makes completely
    # different bitstream decisions than the original encoder,
    # which destroys TikTok's bitstream fingerprint.

    cmd.extend([
        "-c:v", "libx264",
        "-preset", "fast",           # DaVinci "Faster"
        "-tune", "film",             # DaVinci "High Quality" tuning
        "-profile:v", "high",        # H.264 High profile
        "-level", "5.1",             # Support up to 4K
        "-crf", "16",                # DaVinci "Automatic Best" quality

        # ── THE CRITICAL PARAMS THAT BREAK DETECTION ──
        "-bf", "3",                  # B-frames (DaVinci adaptive B-frame)
        "-b_strategy", "2",          # Adaptive B-frame placement (b-adapt=2)
        "-refs", "4",                # Reference frames
        "-rc-lookahead", "16",       # DaVinci Lookahead = 16
        "-aq-mode", "2",             # Variance AQ (auto-redistribute bits)
        "-aq-strength", "1.0",       # DaVinci AQ Strength = 8 → x264 ~1.0
        "-psy-rd", "1.0:0.15",      # Psychovisual optimization
        "-me_method", "umh",         # High quality motion estimation
        "-subq", "7",                # Subpixel motion estimation quality
        "-trellis", "2",             # Rate-distortion optimal quantization

        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
    ])

    # Audio
    if has_audio:
        cmd.extend(["-c:a", "aac", "-b:a", "192k"])

    # Metadata wipe + new identity
    cmd.extend([
        "-map_metadata", "-1",
        "-metadata", f"title={title}",
        "-metadata", f"comment={uuid.uuid4().hex}",
        "-metadata", f"encoder=DaVinci Resolve {random.randint(18,19)}.{random.randint(0,5)}",
        output_path
    ])

    # ── Execute ──
    print(f"[V9] DaVinci emulation mode (libx264 + adaptive B-frames + AQ8)")
    print(f"[V9] Tweaks: zoom={zoom} speed={speed} trim={trim_s}s/{trim_e}s")
    start = time.time()
    result = subprocess.run(cmd, capture_output=True, text=True)
    elapsed = round(time.time() - start, 1)

    if result.returncode != 0:
        err = result.stderr[-600:] if result.stderr else "unknown"
        raise Exception(f"FFmpeg failed: {err}")

    out_mb = os.path.getsize(output_path) / 1024 / 1024
    print(f"[V9] Done in {elapsed}s — {out_mb:.1f} MB")
    p["encode_time"] = elapsed
    p["encoder"] = "x264_davinci_emulation"
    return p
