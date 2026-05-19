"""
Pipeline v2.0 — Spatial Anti-Detection
22 techniques with random selection per job.
All values pre-calculated as literals. No inline math.
"""
import os, json, uuid, random, subprocess, math

PIPELINE_VERSION = "2.0-spatial"
AVAILABLE_FILTERS = set()


def detect_available_filters():
    """Check which FFmpeg filters are available at startup."""
    global AVAILABLE_FILTERS
    result = subprocess.run(["ffmpeg", "-hide_banner", "-filters"],
                            capture_output=True, text=True)
    out = result.stdout + result.stderr
    for f in ["lenscorrection", "vignette", "curves", "unsharp", "rotate",
              "rgbashift", "colorbalance", "acompressor", "extrastereo", "cas"]:
        if f in out:
            AVAILABLE_FILTERS.add(f)
    print(f"[PIPELINE] Available filters: {sorted(AVAILABLE_FILTERS)}")


def select_techniques(has_audio: bool) -> list:
    """Select random subset of techniques for this job."""
    always = ["zoom_crop", "speed", "metadata", "noise_spatial", "reencode"]

    optional = {
        "lens_distortion":       (0.45, "lenscorrection"),
        "micro_rotation":        (0.55, "rotate"),
        "hue_shift":             (0.75, None),
        "color_grading":         (0.65, "colorbalance"),
        "sharpening":            (0.50, "unsharp"),
        "chromatic_aberration":  (0.50, "rgbashift"),
        "vignette":              (0.60, "vignette"),
        "color_overlay":         (0.70, None),
        "frame_trim":            (0.80, None),
        "watermark":             (0.80, None),
    }

    audio_optional = {
        "pitch_shift":    (0.70, None),
        "compressor":     (0.50, "acompressor"),
        "stereo_width":   (0.40, "extrastereo"),
    }

    selected = list(always)
    for tech, (prob, dep) in optional.items():
        if dep and dep not in AVAILABLE_FILTERS:
            continue
        if random.random() < prob:
            selected.append(tech)

    if has_audio:
        for tech, (prob, dep) in audio_optional.items():
            if dep and dep not in AVAILABLE_FILTERS:
                continue
            if random.random() < prob:
                selected.append(tech)

    return selected


def probe_video(path: str) -> dict:
    cmd = ["ffprobe", "-v", "quiet", "-print_format", "json",
           "-show_streams", "-show_format", path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        return {"width": 1080, "height": 1920, "has_audio": False, "fps": 30, "duration": 10}

    data = json.loads(r.stdout)
    w, h, has_audio, fps = 1080, 1920, False, 30
    for s in data.get("streams", []):
        if s.get("codec_type") == "video":
            w = int(s.get("width", 1080))
            h = int(s.get("height", 1920))
            try:
                n, d = s.get("r_frame_rate", "30/1").split("/")
                fps = round(int(n) / int(d), 2)
            except:
                fps = 30
        elif s.get("codec_type") == "audio":
            has_audio = True

    dur = 10
    try:
        dur = float(data.get("format", {}).get("duration", 10))
    except:
        pass

    return {"width": w, "height": h, "has_audio": has_audio, "fps": fps, "duration": dur}


def generate_params(w, h, fps, duration, has_audio, techniques):
    """Generate all random params. Every value is a literal."""
    p = {"pipeline_version": PIPELINE_VERSION, "techniques": techniques}

    # --- Core (always) ---
    p["zoom"] = round(random.uniform(1.02, 1.05), 3)
    p["dx"] = random.randint(-4, 4)
    p["dy"] = random.randint(-4, 4)
    p["speed"] = round(random.uniform(1.01, 1.03), 3)
    p["contrast"] = round(random.uniform(0.97, 1.03), 3)
    p["saturation"] = round(random.uniform(0.96, 1.04), 3)

    # Noise per channel (non-uniform)
    p["noise_c0"] = random.randint(3, 8)
    p["noise_c1"] = random.randint(2, 7)
    p["noise_c2"] = random.randint(3, 9)

    # --- Optional video ---
    if "lens_distortion" in techniques:
        p["lens_k1"] = round(random.uniform(-0.02, 0.02), 4)
        p["lens_k2"] = round(random.uniform(-0.01, 0.01), 4)

    if "micro_rotation" in techniques:
        angle_deg = round(random.uniform(-0.3, 0.3), 3)
        p["rotation_deg"] = angle_deg
        p["rotation_rad"] = round(angle_deg * math.pi / 180, 6)

    if "hue_shift" in techniques:
        p["hue"] = random.randint(-4, 4)

    if "color_grading" in techniques:
        # Split-toning: shadows / midtones / highlights
        for zone in ["s", "m", "h"]:
            p[f"cb_r{zone}"] = round(random.uniform(-0.04, 0.04), 3)
            p[f"cb_g{zone}"] = round(random.uniform(-0.04, 0.04), 3)
            p[f"cb_b{zone}"] = round(random.uniform(-0.04, 0.04), 3)

    if "sharpening" in techniques:
        p["sharp_luma"] = round(random.uniform(0.3, 0.8), 2)
        p["sharp_chroma"] = round(random.uniform(0.1, 0.3), 2)

    if "chromatic_aberration" in techniques:
        shift = random.choice([-2, -1, 1, 2])
        p["ca_rh"] = shift
        p["ca_bh"] = -shift
        p["ca_rv"] = random.choice([-1, 0, 0, 1])
        p["ca_bv"] = -p["ca_rv"]

    if "vignette" in techniques:
        p["vig_angle"] = round(random.uniform(0.75, 1.05), 4)

    if "color_overlay" in techniques:
        p["overlay_r"] = round(random.uniform(-0.03, 0.03), 3)
        p["overlay_g"] = round(random.uniform(-0.03, 0.03), 3)
        p["overlay_b"] = round(random.uniform(-0.03, 0.03), 3)

    if "frame_trim" in techniques:
        p["trim_start_frames"] = random.randint(1, 3)
        p["trim_end_frames"] = random.randint(1, 3)
        p["trim_start_sec"] = round(p["trim_start_frames"] / fps, 4)
        p["trim_end_sec"] = round(p["trim_end_frames"] / fps, 4)

    if "watermark" in techniques:
        p["wm_corner"] = random.choice(["tl", "tr", "bl", "br"])
        p["wm_color"] = random.choice(["red", "green", "blue", "white", "yellow"])
        p["wm_opacity"] = round(random.uniform(0.01, 0.03), 3)
        p["wm_size"] = random.randint(1, 3)

    # --- Optional audio ---
    if "pitch_shift" in techniques:
        p["pitch_factor"] = round(random.uniform(0.985, 1.015), 4)
        p["pitch_rate"] = round(44100 * p["pitch_factor"])  # LITERAL integer

    if "compressor" in techniques:
        p["comp_threshold"] = round(random.uniform(0.05, 0.2), 3)
        p["comp_ratio"] = round(random.uniform(1.5, 3.0), 1)
        p["comp_attack"] = round(random.uniform(10, 40), 0)
        p["comp_release"] = round(random.uniform(150, 400), 0)

    if "stereo_width" in techniques:
        p["stereo_m"] = round(random.uniform(1.02, 1.15), 3)

    return p


def build_video_filters(p, techniques, w, h):
    """Build video filter chain. Order matters for natural look."""
    vf = []

    # 1. Lens distortion (geometry first)
    if "lens_distortion" in techniques:
        vf.append(f"lenscorrection=k1={p['lens_k1']}:k2={p['lens_k2']}")

    # 2. Crop + Scale (always)
    crop_w = int(w / p["zoom"])
    crop_h = int(h / p["zoom"])
    crop_x = max(0, min(int((w - crop_w) / 2 + p["dx"]), w - crop_w))
    crop_y = max(0, min(int((h - crop_h) / 2 + p["dy"]), h - crop_h))
    vf.append(f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y}")
    vf.append(f"scale={w}:{h}")

    # 3. Micro rotation
    if "micro_rotation" in techniques:
        vf.append(f"rotate={p['rotation_rad']}:fillcolor=black:ow={w}:oh={h}")

    # 4. Color: contrast + saturation (always)
    vf.append(f"eq=contrast={p['contrast']}:saturation={p['saturation']}")

    # 5. Hue shift
    if "hue_shift" in techniques and p.get("hue", 0) != 0:
        vf.append(f"hue=h={p['hue']}")

    # 6. Color grading by zones (split-toning via colorbalance)
    if "color_grading" in techniques:
        cb = (f"colorbalance="
              f"rs={p['cb_rs']}:gs={p['cb_gs']}:bs={p['cb_bs']}:"
              f"rm={p['cb_rm']}:gm={p['cb_gm']}:bm={p['cb_bm']}:"
              f"rh={p['cb_rh']}:gh={p['cb_gh']}:bh={p['cb_bh']}")
        vf.append(cb)
    elif "color_overlay" in techniques:
        vf.append(f"colorbalance=rs={p['overlay_r']}:gs={p['overlay_g']}:bs={p['overlay_b']}")

    # 7. Sharpening
    if "sharpening" in techniques:
        vf.append(f"unsharp=5:5:{p['sharp_luma']}:5:5:{p['sharp_chroma']}")

    # 8. Chromatic aberration
    if "chromatic_aberration" in techniques:
        vf.append(f"rgbashift=rh={p['ca_rh']}:bh={p['ca_bh']}:rv={p['ca_rv']}:bv={p['ca_bv']}")

    # 9. Vignette
    if "vignette" in techniques:
        vf.append(f"vignette=angle={p['vig_angle']}")

    # 10. Noise per channel (non-uniform, more natural)
    vf.append(f"noise=c0s={p['noise_c0']}:c1s={p['noise_c1']}:c2s={p['noise_c2']}:allf=t")

    # 11. Invisible watermark
    if "watermark" in techniques:
        s = p["wm_size"]
        corner = p["wm_corner"]
        wm_x = 0 if corner.endswith("l") else w - s
        wm_y = 0 if corner.startswith("t") else h - s
        vf.append(f"drawbox=x={wm_x}:y={wm_y}:w={s}:h={s}:color={p['wm_color']}@{p['wm_opacity']}:t=fill")

    # 12. Speed (always last)
    vf.append(f"setpts=PTS/{p['speed']}")

    return vf


def build_audio_filters(p, techniques):
    """Build audio filter chain."""
    af = []
    speed = max(0.5, min(p["speed"], 2.0))
    af.append(f"atempo={speed:.3f}")

    if "pitch_shift" in techniques:
        af.append(f"asetrate={p['pitch_rate']}")
        af.append(f"aresample=44100")

    if "compressor" in techniques:
        af.append(f"acompressor=threshold={p['comp_threshold']}:ratio={p['comp_ratio']}:"
                  f"attack={int(p['comp_attack'])}:release={int(p['comp_release'])}")

    if "stereo_width" in techniques:
        af.append(f"extrastereo=m={p['stereo_m']}")

    return af


def process_video(input_path: str, output_path: str, use_nvenc: bool = True) -> dict:
    """Full pipeline v2.0 — 22 anti-detection techniques with random selection."""
    info = probe_video(input_path)
    w, h, fps = info["width"], info["height"], info["fps"]
    has_audio = info["has_audio"]
    duration = info["duration"]

    print(f"[PIPE] Video: {w}x{h} @ {fps}fps, audio={has_audio}, dur={duration:.1f}s")

    # Select random techniques for this job
    techniques = select_techniques(has_audio)
    print(f"[PIPE] Techniques ({len(techniques)}): {', '.join(techniques)}")

    # Generate all params (pre-calculated literals)
    p = generate_params(w, h, fps, duration, has_audio, techniques)
    p["original_size"] = f"{w}x{h}"
    p["has_audio"] = has_audio

    # Build filter chains
    vf = build_video_filters(p, techniques, w, h)
    fc = f"[0:v]{','.join(vf)}[v_final]"

    if has_audio:
        af = build_audio_filters(p, techniques)
        fc += f";[0:a]{','.join(af)}[a_final]"

    unique_title = f"clip-{uuid.uuid4().hex[:8]}"

    # Build command
    cmd = ["ffmpeg", "-y"]

    if "frame_trim" in techniques and p.get("trim_start_sec", 0) > 0:
        cmd.extend(["-ss", str(p["trim_start_sec"])])

    cmd.extend(["-i", input_path])

    if "frame_trim" in techniques:
        trim_end = p.get("trim_end_sec", 0)
        target_dur = round(duration - p.get("trim_start_sec", 0) - trim_end, 4)
        if target_dur > 1:
            cmd.extend(["-t", str(target_dur)])

    cmd.extend(["-filter_complex", fc, "-map", "[v_final]"])
    if has_audio:
        cmd.extend(["-map", "[a_final]"])

    if use_nvenc:
        cmd.extend(["-c:v", "h264_nvenc", "-preset", "p6", "-rc", "vbr",
                     "-cq", "18", "-b:v", "10M", "-profile:v", "high", "-pix_fmt", "yuv420p"])
        p["encoder"] = "nvenc_rtx4090"
    else:
        cmd.extend(["-c:v", "libx264", "-preset", "medium", "-crf", "18",
                     "-profile:v", "high", "-pix_fmt", "yuv420p"])
        p["encoder"] = "libx264"

    if has_audio:
        cmd.extend(["-c:a", "aac", "-b:a", "192k"])

    cmd.extend(["-map_metadata", "-1",
                "-metadata", f"title={unique_title}",
                "-metadata", f"comment={uuid.uuid4().hex}",
                "-movflags", "+faststart", output_path])

    # Execute
    import time
    encoder = "NVENC-p6" if use_nvenc else "x264"
    print(f"[PIPE] Encoding ({encoder})...")
    start = time.time()
    result = subprocess.run(cmd, capture_output=True, text=True)
    elapsed = round(time.time() - start, 1)

    if result.returncode != 0:
        err = result.stderr[-600:] if result.stderr else "No error"
        if use_nvenc:
            print(f"[PIPE] NVENC failed, CPU fallback...")
            # Rebuild with x264
            cmd2 = ["ffmpeg", "-y"]
            if "frame_trim" in techniques and p.get("trim_start_sec", 0) > 0:
                cmd2.extend(["-ss", str(p["trim_start_sec"])])
            cmd2.extend(["-i", input_path])
            if "frame_trim" in techniques:
                try:
                    if target_dur > 1:
                        cmd2.extend(["-t", str(target_dur)])
                except:
                    pass
            cmd2.extend(["-filter_complex", fc, "-map", "[v_final]"])
            if has_audio:
                cmd2.extend(["-map", "[a_final]"])
            cmd2.extend(["-c:v", "libx264", "-preset", "medium", "-crf", "18",
                          "-profile:v", "high", "-pix_fmt", "yuv420p"])
            if has_audio:
                cmd2.extend(["-c:a", "aac", "-b:a", "192k"])
            cmd2.extend(["-map_metadata", "-1", "-metadata", f"title={unique_title}",
                          "-metadata", f"comment={uuid.uuid4().hex}",
                          "-movflags", "+faststart", output_path])
            result = subprocess.run(cmd2, capture_output=True, text=True)
            elapsed = round(time.time() - start, 1)
            p["encoder"] = "libx264_fallback"
            if result.returncode != 0:
                raise Exception(f"FFmpeg CPU failed: {result.stderr[-400:]}")
        else:
            raise Exception(f"FFmpeg failed: {err}")

    out_size = os.path.getsize(output_path)
    print(f"[PIPE] Done in {elapsed}s — {out_size / 1024 / 1024:.1f} MB")
    p["ffmpeg_duration_s"] = elapsed
    return p
