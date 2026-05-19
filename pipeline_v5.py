"""Pipeline v5.0 — TikTok Pro Look. Visible but aesthetic changes."""
import os, json, uuid, random, subprocess, time, math

PIPELINE_VERSION = "5.0-pro-look"
FONT_PATH = "C:/Windows/Fonts/arialbd.ttf"
FONT_OK = os.path.exists(FONT_PATH.replace("/", os.sep))

COLOR_GRADES = {
    "teal_orange": {"rs": -0.05, "gs": -0.02, "bs": 0.10, "rh": 0.10, "gh": 0.05, "bh": -0.10},
    "cool_blue":   {"rs": -0.03, "gs": 0.02, "bs": 0.08, "rh": -0.02, "gh": 0.01, "bh": 0.04},
    "warm_vintage":{"rs": 0.08, "gs": 0.04, "bs":-0.06, "rh": 0.04, "gh": 0.02, "bh": -0.03},
    "pastel":      {"rs": 0.03, "gs": 0.05, "bs": 0.08, "rh": 0.02, "gh": 0.04, "bh": 0.06},
    "moody_dark":  {"rs":-0.04, "gs":-0.06, "bs": 0.03, "rh":-0.02, "gh":-0.03, "bh": 0.01},
    "golden_hour": {"rs": 0.06, "gs": 0.03, "bs":-0.04, "rh": 0.08, "gh": 0.05, "bh": -0.02},
}
USERNAMES = ["@creator", "@vibes", "@editpro", "@cliplab",
             "@studioflow", "@proedits", "@reelcut", "@trendmix"]
BAR_COLORS = ["white@0.7", "yellow@0.8", "cyan@0.7", "magenta@0.6"]


def _vary(v, pct=0.3):
    return round(v * random.uniform(1 - pct, 1 + pct), 4)


def _probe(path):
    r = subprocess.run(["ffprobe", "-v", "quiet", "-print_format", "json",
                        "-show_streams", "-show_format", path],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return {"w": 1080, "h": 1920, "audio": False, "fps": 30, "dur": 10}
    d = json.loads(r.stdout)
    w, h, audio, fps = 1080, 1920, False, 30
    for s in d.get("streams", []):
        if s.get("codec_type") == "video":
            w, h = int(s.get("width", 1080)), int(s.get("height", 1920))
            try:
                n, dn = s.get("r_frame_rate", "30/1").split("/")
                fps = round(int(n) / int(dn), 2)
            except: pass
        elif s.get("codec_type") == "audio":
            audio = True
    dur = float(d.get("format", {}).get("duration", 10))
    return {"w": w, "h": h, "audio": audio, "fps": fps, "dur": dur}


def process_video(input_path, output_path, use_nvenc=True):
    info = _probe(input_path)
    w, h, fps = info["w"], info["h"], info["fps"]
    has_audio, duration = info["audio"], info["dur"]
    print(f"[V5] {w}x{h} @{fps}fps audio={has_audio} dur={duration:.1f}s")

    # ── Core params (never darken: contrast/sat >= 1.0) ──
    zoom = round(random.uniform(1.02, 1.04), 3)
    dx, dy = random.randint(-3, 3), random.randint(-3, 3)
    speed = round(random.uniform(1.01, 1.04), 3)
    contrast = round(random.uniform(1.0, 1.06), 3)
    saturation = round(random.uniform(1.0, 1.08), 3)
    brightness = round(random.uniform(0.0, 0.03), 3)
    hue_shift = random.randint(-3, 3)
    do_mirror = random.random() < 0.25
    grain = random.randint(10, 18)

    # Trim
    trim_s = round(random.randint(1, 3) / fps, 4)
    trim_e = round(random.randint(1, 3) / fps, 4)
    trimmed_dur = round(duration - trim_s - trim_e, 3)

    # Audio
    pitch_rate = round(44100 * random.uniform(0.985, 1.015))

    # ── Select optional techniques ──
    grade_name = random.choice(list(COLOR_GRADES.keys()))
    do_inset = random.random() < 0.70
    do_letterbox = (not do_inset) and random.random() < 0.50
    do_vignette = random.random() < 0.60
    do_bar = random.random() < 0.50
    do_watermark = FONT_OK and random.random() < 0.50
    do_reverb = has_audio and random.random() < 0.60
    do_compressor = has_audio and random.random() < 0.70

    # ── Inset params ──
    inset_scale = round(random.uniform(0.90, 0.94), 3) if do_inset else 1.0
    inset_w = int(w * inset_scale) if do_inset else w
    inset_h = int(h * inset_scale) if do_inset else h
    pad_x = (w - inset_w) // 2
    pad_y = (h - inset_h) // 2

    # Letterbox bar height
    lb_h = random.randint(int(h * 0.05), int(h * 0.08)) if do_letterbox else 0

    # Vignette angle (higher = more subtle)
    vig_angle = round(random.uniform(0.75, 0.95), 3)

    # Color grade with variation
    grade = {k: _vary(v) for k, v in COLOR_GRADES[grade_name].items()}

    p = {
        "pipeline_version": PIPELINE_VERSION,
        "zoom": zoom, "speed": speed, "contrast": contrast,
        "saturation": saturation, "brightness": brightness,
        "hue": hue_shift, "mirror": do_mirror, "grain": grain,
        "color_grade": grade_name,
        "inset": do_inset, "inset_scale": inset_scale,
        "letterbox": do_letterbox, "letterbox_h": lb_h,
        "vignette": do_vignette, "progress_bar": do_bar,
        "watermark": do_watermark, "reverb": do_reverb,
        "pitch_rate": pitch_rate,
        "original_size": f"{w}x{h}", "fps": fps, "has_audio": has_audio,
    }

    techs = ["zoom", "speed", "color_grade", "grain", "metadata"]
    if do_mirror: techs.append("mirror")
    if do_inset: techs.append("frame_inset")
    if do_letterbox: techs.append("letterbox")
    if do_vignette: techs.append("vignette")
    if do_bar: techs.append("progress_bar")
    if do_watermark: techs.append("watermark_text")
    if do_reverb: techs.append("reverb")
    if do_compressor: techs.append("compressor")
    p["techniques"] = techs
    print(f"[V5] Look: {grade_name} | Techs ({len(techs)}): {', '.join(techs)}")

    # ── Build video filter chain ──
    crop_w, crop_h = int(w / zoom), int(h / zoom)
    crop_x = max(0, min(int((w - crop_w) / 2 + dx), w - crop_w))
    crop_y = max(0, min(int((h - crop_h) / 2 + dy), h - crop_h))

    vf = [f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y}", f"scale={w}:{h}"]
    vf.append(f"eq=contrast={contrast}:saturation={saturation}:brightness={brightness}")
    if hue_shift != 0:
        vf.append(f"hue=h={hue_shift}")

    cb = f"colorbalance=rs={grade['rs']}:gs={grade['gs']}:bs={grade['bs']}" \
         f":rh={grade['rh']}:gh={grade['gh']}:bh={grade['bh']}"
    vf.append(cb)

    if do_mirror:
        vf.append("hflip")
    if do_vignette:
        vf.append(f"vignette=angle={vig_angle}")

    vf.append(f"noise=c0s={grain}:c1s={max(6, grain-3)}:c2s={grain}:allf=t")

    if do_inset:
        vf.append(f"scale={inset_w}:{inset_h}")
        vf.append(f"pad={w}:{h}:{pad_x}:{pad_y}:black")

    if do_letterbox:
        vf.append(f"drawbox=x=0:y=0:w=iw:h={lb_h}:color=black:t=fill")
        vf.append(f"drawbox=x=0:y=ih-{lb_h}:w=iw:h={lb_h}:color=black:t=fill")

    if do_bar:
        bar_color = random.choice(BAR_COLORS)
        bar_h = random.randint(3, 5)
        vf.append(f"drawbox=x=0:y=ih-{bar_h}:w=iw*t/{trimmed_dur}:h={bar_h}:color={bar_color}:t=fill")

    if do_watermark:
        uname = random.choice(USERNAMES) + str(random.randint(10, 99))
        font_esc = FONT_PATH.replace(":", "\\:")
        vf.append(f"drawtext=fontfile={font_esc}:text='{uname}'"
                  f":fontsize=26:fontcolor=white@0.55:x=w-tw-25:y=h-th-65")

    vf.append(f"setpts=PTS/{speed}")

    fc = f"[0:v]{','.join(vf)}[v_final]"

    # ── Audio filter chain ──
    if has_audio:
        af = [f"atempo={max(0.5, min(speed, 2.0)):.3f}",
              f"asetrate={pitch_rate}", "aresample=44100"]
        if do_compressor:
            thr = round(random.uniform(0.05, 0.15), 3)
            af.append(f"acompressor=threshold={thr}:ratio=2:attack=15:release=200")
        if do_reverb:
            delay = random.randint(30, 60)
            decay = round(random.uniform(0.10, 0.20), 2)
            af.append(f"aecho=0.8:0.85:{delay}:{decay}")
        fc += f";[0:a]{','.join(af)}[a_final]"

    title = f"clip-{uuid.uuid4().hex[:8]}"

    # ── FFmpeg command ──
    cmd = ["ffmpeg", "-y"]
    if trim_s > 0: cmd.extend(["-ss", str(trim_s)])
    cmd.extend(["-i", input_path])
    if trimmed_dur > 1: cmd.extend(["-t", str(trimmed_dur)])

    cmd.extend(["-filter_complex", fc, "-map", "[v_final]"])
    if has_audio: cmd.extend(["-map", "[a_final]"])

    if use_nvenc:
        cmd.extend(["-c:v", "h264_nvenc", "-preset", "p6", "-rc", "vbr",
                     "-cq", "18", "-b:v", "10M", "-profile:v", "high", "-pix_fmt", "yuv420p"])
        p["encoder"] = "nvenc"
    else:
        cmd.extend(["-c:v", "libx264", "-preset", "medium", "-crf", "18",
                     "-profile:v", "high", "-pix_fmt", "yuv420p"])
        p["encoder"] = "x264"

    if has_audio: cmd.extend(["-c:a", "aac", "-b:a", "192k"])
    cmd.extend(["-map_metadata", "-1", "-metadata", f"title={title}",
                "-metadata", f"comment={uuid.uuid4().hex}",
                "-movflags", "+faststart", output_path])

    # ── Execute ──
    print(f"[V5] Encoding ({'NVENC' if use_nvenc else 'CPU'})...")
    start = time.time()
    result = subprocess.run(cmd, capture_output=True, text=True)
    elapsed = round(time.time() - start, 1)

    if result.returncode != 0:
        if use_nvenc:
            print("[V5] NVENC failed, CPU fallback...")
            for i, c in enumerate(cmd):
                if c == "h264_nvenc": cmd[i] = "libx264"
                if c == "p6": cmd[i] = "medium"
            result = subprocess.run(cmd, capture_output=True, text=True)
            elapsed = round(time.time() - start, 1)
            p["encoder"] = "x264_fallback"
            if result.returncode != 0:
                raise Exception(f"FFmpeg failed: {result.stderr[-500:]}")
        else:
            raise Exception(f"FFmpeg failed: {result.stderr[-500:]}")

    out_mb = os.path.getsize(output_path) / 1024 / 1024
    print(f"[V5] Done in {elapsed}s — {out_mb:.1f} MB")
    p["encode_time"] = elapsed
    return p
