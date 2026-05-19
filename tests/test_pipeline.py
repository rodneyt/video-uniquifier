"""
Tests for the video uniquification pipeline.
Validates that filter strings never contain math expressions,
parameters are within valid ranges, and the pipeline is robust.
"""
import re
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from worker.pipeline import (
    build_video_filter,
    build_audio_filter,
    generate_random_params,
    validate_filter_string,
    validate_command,
    _INVALID_FILTER_PATTERNS,
)


def test_audio_filter_no_expressions():
    """Validate that build_audio_filter() NEVER returns strings with math ops."""
    for _ in range(200):
        params = generate_random_params()
        af = build_audio_filter(params)
        
        # Must not contain *, +, / between digits
        assert not _INVALID_FILTER_PATTERNS.search(af), \
            f"Audio filter contains math expression: {af}"
        
        # Must not contain 'asetrate' (removed by design)
        assert "asetrate" not in af, f"Audio filter should not use asetrate: {af}"
        
        # Must not contain 'aresample' (removed by design)
        assert "aresample" not in af, f"Audio filter should not use aresample: {af}"
        
        # atempo value must be a literal float
        match = re.search(r'atempo=([\d.]+)', af)
        assert match, f"No atempo found in: {af}"
        val = float(match.group(1))
        assert 0.5 <= val <= 2.0, f"atempo={val} out of range in: {af}"


def test_video_filter_no_expressions():
    """Validate that build_video_filter() never returns strings with math ops."""
    for _ in range(200):
        params = generate_random_params()
        vf = build_video_filter(1080, 1920, params)
        
        assert not _INVALID_FILTER_PATTERNS.search(vf), \
            f"Video filter contains math expression: {vf}"


def test_random_params_valid():
    """Run 100 iterations and verify all parameters are in valid ranges."""
    for _ in range(100):
        p = generate_random_params()
        
        assert 1.02 <= p["zoom"] <= 1.04, f"zoom={p['zoom']} out of range"
        assert -3 <= p["dx"] <= 3, f"dx={p['dx']} out of range"
        assert -3 <= p["dy"] <= 3, f"dy={p['dy']} out of range"
        assert 0.5 <= p["speed"] <= 2.0, f"speed={p['speed']} out of range"
        assert 0.9 <= p["contrast"] <= 1.1, f"contrast={p['contrast']} out of range"
        assert 0.9 <= p["saturation"] <= 1.1, f"saturation={p['saturation']} out of range"
        assert -10 <= p["hue"] <= 10, f"hue={p['hue']} out of range"
        assert 0 <= p["noise"] <= 20, f"noise={p['noise']} out of range"


def test_validate_filter_string_catches_expressions():
    """Ensure validate_filter_string catches math expressions."""
    bad_strings = [
        "asetrate=44100*0.998",
        "asetrate=44100+100",
        "asetrate=44100/2",
        "eq=brightness=0.5*2",
    ]
    for s in bad_strings:
        try:
            validate_filter_string(s)
            assert False, f"Should have raised ValueError for: {s}"
        except ValueError:
            pass  # Expected
    
    # Good strings should pass
    good_strings = [
        "atempo=1.020",
        "eq=contrast=1.02:saturation=0.98",
        "crop=1046:1860:17:30,scale=1080:1920",
        "noise=alls=5:allf=t",
        "hue=h=-3",
    ]
    for s in good_strings:
        validate_filter_string(s)  # Should not raise


def test_validate_command_catches_bad_atempo():
    """Ensure validate_command catches out-of-range atempo."""
    bad_cmd = ["ffmpeg", "-filter_complex", "[0:a]atempo=0.1[a_final]"]
    try:
        validate_command(bad_cmd)
        assert False, "Should have raised ValueError for atempo=0.1"
    except ValueError:
        pass


def test_build_audio_filter_clamps_speed():
    """Ensure build_audio_filter clamps speed to [0.5, 2.0]."""
    # Edge case: speed way too low
    params = {"speed": 0.1}
    af = build_audio_filter(params)
    val = float(re.search(r'atempo=([\d.]+)', af).group(1))
    assert val >= 0.5, f"atempo={val} below minimum"
    
    # Edge case: speed way too high
    params = {"speed": 5.0}
    af = build_audio_filter(params)
    val = float(re.search(r'atempo=([\d.]+)', af).group(1))
    assert val <= 2.0, f"atempo={val} above maximum"


if __name__ == "__main__":
    print("Running pipeline tests...")
    
    tests = [
        test_audio_filter_no_expressions,
        test_video_filter_no_expressions,
        test_random_params_valid,
        test_validate_filter_string_catches_expressions,
        test_validate_command_catches_bad_atempo,
        test_build_audio_filter_clamps_speed,
    ]
    
    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  ✅ {test.__name__}")
            passed += 1
        except Exception as e:
            print(f"  ❌ {test.__name__}: {e}")
            failed += 1
    
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed > 0 else 0)
