"""
Particle Overlay Generator — Animated colored pixel particles.
Generates PNG sequences with moving/blinking particles on transparent background.
Used as FFmpeg overlay to break TikTok perceptual hash detection.
"""
import os, random, math
from PIL import Image, ImageDraw

COLORS = [
    (255, 48, 48),    # Red
    (48, 255, 48),    # Green
    (48, 255, 255),   # Cyan
    (255, 48, 255),   # Magenta
    (255, 255, 255),  # White
    (255, 255, 48),   # Yellow
]

PRESETS = {
    "subtle": {
        "count": (100, 200),
        "size_max": 1,
        "colors": [(48, 255, 255), (255, 255, 255)],  # cyan + white only
        "opacity_high_pct": 0.15,
        "opacity_high": (100, 180),
        "opacity_low": (60, 120),
        "speed_range": (-1, 1),
        "blink_pct": 0.10,
        "static_pct": 0.20,
    },
    "medium": {
        "count": (250, 350),
        "size_max": 2,
        "colors": None,  # random 4 from palette
        "opacity_high_pct": 0.30,
        "opacity_high": (150, 230),
        "opacity_low": (80, 150),
        "speed_range": (-2, 2),
        "blink_pct": 0.15,
        "static_pct": 0.10,
    },
    "heavy": {
        "count": (400, 600),
        "size_max": 3,
        "colors": COLORS,  # full palette
        "opacity_high_pct": 0.35,
        "opacity_high": (180, 255),
        "opacity_low": (100, 170),
        "speed_range": (-3, 3),
        "blink_pct": 0.20,
        "static_pct": 0.05,
    },
}


def choose_preset():
    """Random preset selection weighted: subtle 40%, medium 40%, heavy 20%."""
    r = random.random()
    if r < 0.40:
        return "subtle"
    elif r < 0.80:
        return "medium"
    else:
        return "heavy"


class Particle:
    __slots__ = ['x', 'y', 'vx', 'vy', 'color', 'size', 'alpha', 'ptype', 'blink_period']

    def __init__(self, w, h, preset_cfg):
        self.x = random.randint(0, w - 1)
        self.y = random.randint(0, h - 1)

        sp = preset_cfg["speed_range"]
        self.vx = random.uniform(sp[0], sp[1])
        self.vy = random.uniform(sp[0], sp[1])

        colors = preset_cfg["colors"] or random.sample(COLORS, min(4, len(COLORS)))
        self.color = random.choice(colors)
        self.size = random.randint(1, preset_cfg["size_max"])

        if random.random() < preset_cfg["opacity_high_pct"]:
            self.alpha = random.randint(*preset_cfg["opacity_high"])
        else:
            self.alpha = random.randint(*preset_cfg["opacity_low"])

        # Type: moving (default), blinking, or static
        roll = random.random()
        if roll < preset_cfg["static_pct"]:
            self.ptype = "static"
            self.vx = self.vy = 0
        elif roll < preset_cfg["static_pct"] + preset_cfg["blink_pct"]:
            self.ptype = "blink"
            self.blink_period = random.randint(3, 6)
        else:
            self.ptype = "moving"
            self.blink_period = 0

    def is_visible(self, frame_num):
        if self.ptype == "blink":
            return (frame_num // self.blink_period) % 2 == 0
        return True

    def get_pos(self, frame_num, w, h):
        if self.ptype == "static":
            return int(self.x) % w, int(self.y) % h
        x = (self.x + self.vx * frame_num) % w
        y = (self.y + self.vy * frame_num) % h
        return int(x), int(y)


def generate_frames(output_dir, width=1080, height=1920, num_frames=60, preset_name=None):
    """Generate particle PNG sequence. Returns preset info dict."""
    if preset_name is None:
        preset_name = choose_preset()
    cfg = PRESETS[preset_name]

    count = random.randint(*cfg["count"])
    particles = [Particle(width, height, cfg) for _ in range(count)]

    os.makedirs(output_dir, exist_ok=True)

    for f in range(num_frames):
        img = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        for p in particles:
            if not p.is_visible(f):
                continue
            x, y = p.get_pos(f, width, height)
            s = p.size
            fill = (*p.color, p.alpha)
            if s == 1:
                img.putpixel((x, y), fill)
            else:
                draw.ellipse([x, y, x + s, y + s], fill=fill)

        img.save(os.path.join(output_dir, f"{f:03d}.png"), "PNG")

    info = {
        "preset": preset_name,
        "particle_count": count,
        "num_frames": num_frames,
        "size_max": cfg["size_max"],
        "speed_range": cfg["speed_range"],
    }
    print(f"[PARTICLES] Generated {num_frames} frames, {count} particles, preset={preset_name}")
    return info


if __name__ == "__main__":
    import sys, time
    preset = sys.argv[1] if len(sys.argv) > 1 else None
    start = time.time()
    info = generate_frames("_test_particles", preset_name=preset)
    print(f"Done in {time.time()-start:.1f}s: {info}")
