"""
Pipeline v10.0 — Vertical 4K Nuke (Options A+B+C combined)

Keeps the video VERTICAL while applying all 3 evasion techniques:
  A) Upscale to 4K vertical (2160x3840) — recalculates every pixel
  B) Blur padding top/bottom — adds unique content to change frame composition
  C) Double encode (H.264 -> HEVC intermediate -> H.264 final) — completely 
     different bitstream from two different encoder passes

This pipeline is for users who want to keep vertical format for TikTok
while still bypassing duplicate content detection.
"""
import os, json, uuid, random, subprocess, time

PIPELINE_VERSION = "10.0-vertical-4k-nuke"


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

    # ═══════════════════════════════════════════════════════
    # OPTION A: Upscale to 4K vertical (2160x3840)
    # ═══════════════════════════════════════════════════════
    out_w = 2160
    out_h = 3840
    
    # ═══════════════════════════════════════════════════════
    # OPTION B: Blur padding top/bottom
    # Add 3-6% blur bars to top and bottom, making the frame
    # slightly taller. The blur comes from the video itself.
    # ═══════════════════════════════════════════════════════
    blur_pad_pct = round(random.uniform(0.03, 0.06), 3)
    blur_pad_px = int(out_h * blur_pad_pct)
    blur_pad_px = (blur_pad_px // 2) * 2  # even
    content_h = out_h - (blur_pad_px * 2)  # space for the actual content
    content_h = (content_h // 2) * 2

    blur_sigma = random.randint(35, 50)

    print(f"[V10] {w}x{h} -> VERTICAL 4K {out_w}x{out_h} (blur pad {blur_pad_px}px top/bottom)")

    # ── Minimal visual tweaks ──
    zoom = round(random.uniform(1.01, 1.03), 3)
    dx, dy = random.randint(-2, 2), random.randint(-2, 2)
    speed = round(random.uniform(1.005, 1.02), 3)
    contrast = round(random.uniform(1.00, 1.03), 3)
    saturation = round(random.uniform(1.00, 1.04), 3)
    hue_shift = random.choice([-2, -1, 0, 1, 2])

    trim_s = round(random.uniform(0.04, 0.15), 3)
    trim_e = round(random.uniform(0.04, 0.15), 3)
    trimmed_dur = round(duration - trim_s - trim_e, 3)
    if trimmed_dur < 1.0:
        trim_s = trim_e = 0
        trimmed_dur = duration

    pitch_rate = round(a_rate * random.uniform(0.995, 1.005))

    crop_w = int(w / zoom)
    crop_h = int(h / zoom)
    crop_x = max(0, min(int((w - crop_w) / 2 + dx), w - crop_w))
    crop_y = max(0, min(int((h - crop_h) / 2 + dy), h - crop_h))

    p = {
        "pipeline_version": PIPELINE_VERSION,
        "output_res": f"{out_w}x{out_h}",
        "blur_pad": blur_pad_px,
        "zoom": zoom, "speed": speed,
        "contrast": contrast, "saturation": saturation, "hue": hue_shift,
        "trim_start": trim_s, "trim_end": trim_e,
        "pitch_rate": pitch_rate,
        "original_size": f"{w}x{h}", "fps": fps,
    }

    # ── filter_complex: blurred BG (stretched) + foreground (fit) ──
    fc_parts = [
        # Background: stretch to fill full frame, heavy blur
        f"[0:v]scale={out_w}:{out_h}:force_original_aspect_ratio=increase,"
        f"crop={out_w}:{out_h},"
        f"gblur=sigma={blur_sigma},"
        f"eq=brightness=-0.03"
        f"[bg]",

        # Foreground: crop+zoom, scale to fit content area, keep aspect ratio
        f"[0:v]crop={crop_w}:{crop_h}:{crop_x}:{crop_y},"
        f"scale={out_w}:{content_h}:flags=lanczos,"
        f"eq=contrast={contrast}:saturation={saturation}"
        + (f",hue=h={hue_shift}" if hue_shift != 0 else "")
        + f"[fg]",

        # Overlay foreground centered on blurred background
        f"[bg][fg]overlay=0:{blur_pad_px},"
        f"setpts=PTS/{speed}"
        f"[v_final]",
    ]

    fc = ";".join(fc_parts)

    if has_audio:
        af_parts = [
            f"atempo={speed:.3f}",
            f"asetrate={pitch_rate}",
            f"aresample={a_rate}",
        ]
        fc += f";[0:a]{','.join(af_parts)}[a_final]"

    # ═══════════════════════════════════════════════════════
    # OPTION C: Double encode (HEVC intermediate -> H.264 final)
    # First pass: encode to HEVC (completely different codec)
    # Second pass: encode from HEVC to H.264 (different bitstream)
    # ═══════════════════════════════════════════════════════
    
    # Temp file for HEVC intermediate
    intermediate = output_path + ".hevc_intermediate.mp4"
    
    title = f"clip-{uuid.uuid4().hex[:8]}"

    # ── PASS 1: Input -> HEVC intermediate ──
    cmd1 = ["ffmpeg", "-y"]
    if trim_s > 0: cmd1.extend(["-ss", str(trim_s)])
    cmd1.extend(["-i", input_path])
    if trimmed_dur > 1 and trim_e > 0: cmd1.extend(["-t", str(trimmed_dur)])
    cmd1.extend([
        "-filter_complex", fc, "-map", "[v_final]",
    ])
    if has_audio: cmd1.extend(["-map", "[a_final]"])
    cmd1.extend([
        "-c:v", "libx265", "-preset", "fast", "-crf", "18",
        "-pix_fmt", "yuv420p",
    ])
    if has_audio: cmd1.extend(["-c:a", "aac", "-b:a", "192k"])
    cmd1.extend(["-movflags", "+faststart", intermediate])

    # ── PASS 2: HEVC -> H.264 final (DaVinci-style encoder settings) ──
    cmd2 = [
        "ffmpeg", "-y", "-i", intermediate,
        "-c:v", "libx264",
        "-preset", "fast",
        "-tune", "film",
        "-profile:v", "high",
        "-level", "5.1",
        "-crf", "16",
        "-bf", "3",
        "-b_strategy", "2",
        "-refs", "4",
        "-rc-lookahead", "16",
        "-aq-mode", "2",
        "-aq-strength", "1.0",
        "-psy-rd", "1.0:0.15",
        "-me_method", "umh",
        "-subq", "7",
        "-trellis", "2",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
    ]
    if has_audio: cmd2.extend(["-c:a", "copy"])  # Audio already encoded
    cmd2.extend([
        "-map_metadata", "-1",
        "-metadata", f"title={title}",
        "-metadata", f"comment={uuid.uuid4().hex}",
        output_path
    ])

    # ── Execute Pass 1 (HEVC) ──
    print(f"[V10] Pass 1: Encoding to HEVC intermediate...")
    start = time.time()
    r1 = subprocess.run(cmd1, capture_output=True, text=True)
    t1 = round(time.time() - start, 1)

    if r1.returncode != 0:
        err = r1.stderr[-500:] if r1.stderr else "unknown"
        try: os.remove(intermediate)
        except: pass
        raise Exception(f"Pass 1 (HEVC) failed: {err}")

    print(f"[V10] Pass 1 done in {t1}s")

    # ── Execute Pass 2 (H.264 final) ──
    print(f"[V10] Pass 2: Re-encoding HEVC -> H.264 (DaVinci settings)...")
    r2 = subprocess.run(cmd2, capture_output=True, text=True)
    elapsed = round(time.time() - start, 1)

    # Cleanup intermediate
    try: os.remove(intermediate)
    except: pass

    if r2.returncode != 0:
        err = r2.stderr[-500:] if r2.stderr else "unknown"
        raise Exception(f"Pass 2 (H.264) failed: {err}")

    out_mb = os.path.getsize(output_path) / 1024 / 1024
    print(f"[V10] Done in {elapsed}s ({t1}s HEVC + {round(elapsed-t1,1)}s H.264) -- {out_mb:.1f} MB")
    p["encode_time"] = elapsed
    p["encoder"] = "double_encode_hevc_to_h264"
    return p
