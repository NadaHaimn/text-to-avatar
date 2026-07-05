# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
"""
TEST: Convert ONE word from KArSL-502 to SiGML format.

Usage:
    python tools/test_one_word.py --sign-id 32 --word ا

This will:
1. Find the best video clip for that word
2. Extract hand/pose landmarks with MediaPipe
3. Map landmarks to HamNoSys tags
4. Generate a .sigml file
5. Copy it to web-simulator/sigml/ and data/sigml/

Then restart the server and test typing the word in the browser.
"""

import argparse
import urllib.request
import re
import os
import math
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np

# ── Paths ────────────────────────────────────────────────────────────────────
SCRIPT_DIR   = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
DATA_SIGML   = PROJECT_ROOT / "data" / "sigml"
WEB_SIGML    = PROJECT_ROOT / "web-simulator" / "sigml"
MODEL_DIR    = SCRIPT_DIR / "models"
DATASET_ROOT = Path(r"E:\Graduation project\KArSL-502\01\test")

MODEL_DIR.mkdir(parents=True, exist_ok=True)
DATA_SIGML.mkdir(parents=True, exist_ok=True)
WEB_SIGML.mkdir(parents=True, exist_ok=True)

# ── MediaPipe model download ──────────────────────────────────────────────────
POSE_MODEL  = MODEL_DIR / "pose_landmarker_lite.task"
HAND_MODEL  = MODEL_DIR / "hand_landmarker.task"
POSE_URL    = ("https://storage.googleapis.com/mediapipe-models/"
               "pose_landmarker/pose_landmarker_lite/float16/latest/"
               "pose_landmarker_lite.task")
HAND_URL    = ("https://storage.googleapis.com/mediapipe-models/"
               "hand_landmarker/hand_landmarker/float16/latest/"
               "hand_landmarker.task")

def ensure_models():
    for url, path in [(POSE_URL, POSE_MODEL), (HAND_URL, HAND_MODEL)]:
        if not path.exists():
            print(f"  Downloading {path.name}...")
            urllib.request.urlretrieve(url, path)
            print(f"  Saved: {path}")

# ── Frame sorting ─────────────────────────────────────────────────────────────
def sort_key(p: Path) -> int:
    m = re.search(r'(\d+)$', p.stem)
    return int(m.group()) if m else 0

# ── MediaPipe extraction ──────────────────────────────────────────────────────
def extract_from_folder(folder: Path):
    """Extract pose+hand landmarks from all frames in a folder."""
    from mediapipe.tasks.python.core import base_options as _bo
    from mediapipe.tasks.python.vision import (
        PoseLandmarker, PoseLandmarkerOptions,
        HandLandmarker, HandLandmarkerOptions,
        RunningMode,
    )

    pose_opts = PoseLandmarkerOptions(
        base_options=_bo.BaseOptions(model_asset_path=str(POSE_MODEL)),
        running_mode=RunningMode.VIDEO,
        num_poses=1,
        min_pose_detection_confidence=0.4,
        min_pose_presence_confidence=0.4,
        min_tracking_confidence=0.4,
    )
    hand_opts = HandLandmarkerOptions(
        base_options=_bo.BaseOptions(model_asset_path=str(HAND_MODEL)),
        running_mode=RunningMode.VIDEO,
        num_hands=2,
        min_hand_detection_confidence=0.4,
        min_hand_presence_confidence=0.4,
        min_tracking_confidence=0.4,
    )

    frames = sorted(folder.glob("*.jpg"), key=sort_key)
    results = []

    with (PoseLandmarker.create_from_options(pose_opts) as pose_lmk,
          HandLandmarker.create_from_options(hand_opts) as hand_lmk):
        for i, fp in enumerate(frames):
            img = cv2.imread(str(fp))
            if img is None:
                continue
            rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            ts = int(i * 1000 / 30.0)

            pose_r = pose_lmk.detect_for_video(mp_img, ts)
            hand_r = hand_lmk.detect_for_video(mp_img, ts)

            pose_lms = pose_r.pose_landmarks[0] if pose_r.pose_landmarks else None

            left_hand = right_hand = None
            for j, hedness in enumerate(hand_r.handedness):
                if not hedness:
                    continue
                label = hedness[0].category_name
                lms   = hand_r.hand_landmarks[j]
                if label == "Left":
                    left_hand = lms
                else:
                    right_hand = lms

            results.append({
                "pose": pose_lms,
                "left":  left_hand,
                "right": right_hand,
            })

    return results

# ── Best clip selection ───────────────────────────────────────────────────────
def pick_best_clip(word_folder: Path) -> Path:
    """Pick subfolder with highest hand detection rate."""
    best_folder, best_score = None, -1
    for sub in sorted(word_folder.iterdir()):
        if not sub.is_dir():
            continue
        imgs = list(sub.glob("*.jpg"))
        if not imgs:
            continue
        # Use frame count as proxy for quality (more frames = longer, clearer sign)
        score = len(imgs)
        if score > best_score:
            best_score = score
            best_folder = sub
    return best_folder

# ── HamNoSys analysis helpers ─────────────────────────────────────────────────
def pt(lms, idx):
    """Get [x,y,z] from landmark list."""
    l = lms[idx]
    return np.array([l.x, l.y, l.z])

def dist(a, b):
    return float(np.linalg.norm(a - b))

def finger_curl(lms, tip_i, dip_i, pip_i, mcp_i, wrist_i=0):
    """
    Returns 0.0 (fully curled/fist) to 1.0 (fully extended).
    Uses tip-to-wrist distance normalised by mcp-to-wrist distance.
    """
    wrist = pt(lms, wrist_i)
    mcp   = pt(lms, mcp_i)
    tip   = pt(lms, tip_i)
    d_mcp = dist(wrist, mcp)
    if d_mcp < 1e-6:
        return 0.5
    return min(dist(wrist, tip) / (d_mcp * 2.2), 1.0)

def analyze_hand(lms):
    """Analyse a hand's landmarks. Returns dict of properties."""
    if lms is None:
        return None

    wrist = pt(lms, 0)

    # Extension ratios  (0=curled, 1=extended)
    index  = finger_curl(lms, 8,  7,  6,  5)
    middle = finger_curl(lms, 12, 11, 10, 9)
    ring   = finger_curl(lms, 16, 15, 14, 13)
    pinky  = finger_curl(lms, 20, 19, 18, 17)
    thumb  = finger_curl(lms, 4,  3,  2,  1)

    # Pinch: distance between thumb tip and index tip
    thumb_tip = pt(lms, 4)
    index_tip = pt(lms, 8)
    hand_size = dist(wrist, pt(lms, 9))   # wrist to middle MCP
    pinch_dist = dist(thumb_tip, index_tip) / (hand_size + 1e-6)

    # Palm normal (direction palm faces): cross product of index-MCP→pinky-MCP × wrist→index-MCP
    v1 = pt(lms, 5)  - pt(lms, 0)
    v2 = pt(lms, 17) - pt(lms, 0)
    normal = np.cross(v1, v2)
    norm_len = np.linalg.norm(normal)
    if norm_len > 1e-6:
        normal = normal / norm_len

    # Wrist position (raw, for location detection against pose)
    return {
        "ext": {"index": index, "middle": middle, "ring": ring,
                "pinky": pinky, "thumb": thumb},
        "pinch_dist": pinch_dist,
        "normal": normal,
        "wrist": wrist,
    }

# ── HamNoSys tag generators ───────────────────────────────────────────────────
def thumb_direction_tags(lms):
    """When thumb is the dominant extended digit, compute its pointing direction."""
    if lms is None:
        return []
    # Thumb tip vs thumb base (MCP)
    tip = pt(lms, 4)
    mcp = pt(lms, 2)
    vec = tip - mcp   # vector from base to tip
    # Normalise
    norm = np.linalg.norm(vec)
    if norm < 1e-6:
        return []
    vec = vec / norm
    tx, ty = float(vec[0]), float(vec[1])
    # In MediaPipe image coords: y increases downward
    # Thumb pointing up → ty strongly negative
    if ty < -0.5:
        return ["<hamextfingeru/>"]
    elif ty > 0.5:
        return ["<hamextfingerd/>"]
    elif tx > 0.3:
        return ["<hamextfingero/>"]
    elif tx < -0.3:
        return ["<hamextfingeri/>"]
    return ["<hamextfingero/>"]

def handshape_tags(h, lms=None):
    """Map hand analysis to HamNoSys handshape tags."""
    if h is None:
        return ["<hamfist/>"]

    e = h["ext"]
    pd = h["pinch_dist"]

    num_ext  = sum(1 for v in [e["index"], e["middle"], e["ring"], e["pinky"]] if v > 0.72)
    num_curl = sum(1 for v in [e["index"], e["middle"], e["ring"], e["pinky"]] if v < 0.45)
    thumb_out = e["thumb"] > 0.65

    # Pinch (thumb-tip touching index-tip)
    if pd < 0.18:
        return ["<hampinchall/>", "<hamfingerstraightmod/>"]

    # Full fist
    if num_curl >= 3:
        tags = ["<hamfist/>"]
        if thumb_out:
            tags.append("<hamthumboutmod/>")
        return tags

    # Flat hand / all fingers extended
    if num_ext >= 4:
        tags = ["<hamfinger2345/>"]
        if thumb_out:
            tags.append("<hamthumbopenmod/>")
        return tags

    # Only index extended
    if e["index"] > 0.72 and e["middle"] < 0.5 and e["ring"] < 0.5 and e["pinky"] < 0.5:
        return ["<hamfinger2/>"]

    # Index + middle
    if e["index"] > 0.72 and e["middle"] > 0.72 and e["ring"] < 0.5 and e["pinky"] < 0.5:
        return ["<hamfinger23/>"]

    # Three fingers
    if e["index"] > 0.72 and e["middle"] > 0.72 and e["ring"] > 0.72 and e["pinky"] < 0.5:
        return ["<hamfinger234/>"]

    return ["<hamfinger2345/>"]

def palm_orientation_tag(h, is_fist_thumb_up=False):
    """Map palm normal to HamNoSys palm-orientation tag."""
    if h is None:
        return "<hampalmu/>"

    # Special case: fist with thumb pointing up (thumbs-up sign)
    # Palm must face INWARD toward body so the thumb-out direction = UP
    if is_fist_thumb_up:
        return "<hampalmi/>"

    n = h["normal"]
    x, y, z = float(n[0]), float(n[1]), float(n[2])
    abs_x, abs_y, abs_z = abs(x), abs(y), abs(z)
    dominant = max(abs_x, abs_y, abs_z)

    if dominant == abs_y:
        return "<hampalmu/>" if y < 0 else "<hampalmd/>"
    if dominant == abs_x:
        return "<hampalmr/>" if x > 0 else "<hampalml/>"
    return "<hampalmo/>" if z > 0 else "<hampalmi/>"

def location_tag(hand_info, pose_lms, debug=False):
    """
    Map wrist position to HamNoSys location tag.

    Strategy:
    - Use SHOULDER as the primary anchor (more reliable than nose-to-hip range)
    - Use z-depth: if wrist is significantly in FRONT of the body → neutral space
    - Use y position relative to shoulder for body-contact locations
    """
    if hand_info is None or pose_lms is None:
        return "<hamneutralspace/>"

    # Key pose landmarks
    nose_y      = pose_lms[0].y
    l_sh_y      = pose_lms[11].y
    r_sh_y      = pose_lms[12].y
    shoulder_y  = (l_sh_y + r_sh_y) / 2.0
    l_hip_y     = pose_lms[23].y
    r_hip_y     = pose_lms[24].y
    hip_y       = (l_hip_y + r_hip_y) / 2.0

    # Shoulder z (body surface reference)
    shoulder_z  = (pose_lms[11].z + pose_lms[12].z) / 2.0
    wrist_z     = float(hand_info["wrist"][2])
    wrist_y     = float(hand_info["wrist"][1])

    torso_h     = max(hip_y - shoulder_y, 0.01)

    # z-depth: how far in front of body is the wrist?
    # In MediaPipe, z is relative depth - lower = closer to camera
    z_forward   = shoulder_z - wrist_z   # positive = hand is in front of body

    if debug:
        print(f"  [DEBUG] nose_y={nose_y:.3f} shoulder_y={shoulder_y:.3f} hip_y={hip_y:.3f}")
        print(f"  [DEBUG] wrist_y={wrist_y:.3f} wrist_z={wrist_z:.3f} shoulder_z={shoulder_z:.3f}")
        print(f"  [DEBUG] z_forward={z_forward:.3f} torso_h={torso_h:.3f}")
        # Position relative to shoulder
        dy = wrist_y - shoulder_y
        print(f"  [DEBUG] dy_from_shoulder={dy:.3f} (negative=above shoulder)")

    # --- Neutral space detection (hand held OUT in front of body) ---
    # If wrist is significantly forward AND at body height → neutral space
    if z_forward > 0.08:
        # Hand is in front of body - now determine height zone
        if wrist_y < shoulder_y - 0.04:
            # Above shoulder level while extended → upper neutral / head area
            if wrist_y < nose_y:
                return "<hamforehead/>"
            return "<hamlips/>"
        elif wrist_y < shoulder_y + torso_h * 0.4:
            return "<hamneutralspace/>"    # mid-torso forward = classic neutral
        else:
            return "<hamneutralspace/>"    # lower torso forward

    # --- Body-contact locations (hand near body surface) ---
    dy = wrist_y - shoulder_y   # negative = above shoulder

    if dy < -(torso_h * 0.3):   # Well above shoulder = face area
        if wrist_y < nose_y - 0.02:
            return "<hamforehead/>"
        elif wrist_y < nose_y + 0.04:
            return "<hamnose/>"
        else:
            return "<hamlips/>"
    elif dy < 0:                 # Slightly above or at shoulder
        return "<hamshouldertop/>"
    elif dy < torso_h * 0.35:   # Upper torso
        return "<hamchest/>"
    elif dy < torso_h * 0.75:   # Mid torso
        return "<hamstomach/>"
    else:
        return "<hamneutralspace/>"  # very low

def movement_tags(frames_data, hand_key="right"):
    """Detect movement direction from wrist trajectory across frames."""
    positions = []
    for f in frames_data:
        h = analyze_hand(f.get(hand_key))
        if h is not None:
            positions.append(h["wrist"])

    if len(positions) < 4:
        return []

    start = np.mean(positions[:max(1, len(positions)//5)], axis=0)
    end   = np.mean(positions[-(max(1, len(positions)//5)):], axis=0)
    delta = end - start

    dx, dy = float(delta[0]), float(delta[1])
    magnitude = math.hypot(dx, dy)

    if magnitude < 0.04:    # Essentially static
        return []

    tags = []
    if abs(dx) > abs(dy):
        tags.append("<hammoveo/>" if dx > 0 else "<hammovei/>")
    else:
        tags.append("<hammoveu/>" if dy < 0 else "<hammoved/>")

    if magnitude < 0.08:
        tags.append("<hamsmallmod/>")
    elif magnitude > 0.18:
        tags.append("<hamlargemod/>")

    return tags

# ── SiGML XML builder ─────────────────────────────────────────────────────────
def build_sigml(tags: list, gloss: str = "") -> str:
    inner = "\n\t\t\t".join(tags)
    return f"""<sigml>

\t<hns_sign gloss="{gloss}">
\t\t<hamnosys_nonmanual>
\t\t</hamnosys_nonmanual>
\t\t<hamnosys_manual>
\t\t\t{inner}
\t\t</hamnosys_manual>
\t</hns_sign>

</sigml>"""

# ── Main test function ────────────────────────────────────────────────────────
def test_one(sign_id: int, word: str):
    word_folder = DATASET_ROOT / f"{sign_id:04d}"
    if not word_folder.exists():
        print(f"ERROR: Folder not found: {word_folder}")
        sys.exit(1)

    print(f"\n=== Testing: SignID={sign_id:04d}  Word='{word}' ===")

    # 1. Pick best clip
    print("Step 1: Selecting best video clip...")
    best = pick_best_clip(word_folder)
    if best is None:
        print("ERROR: No valid subfolder found.")
        sys.exit(1)
    print(f"  Using: {best.name}  ({len(list(best.glob('*.jpg')))} frames)")

    # 2. Ensure models
    print("Step 2: Checking MediaPipe models...")
    ensure_models()

    # 3. Extract landmarks
    print("Step 3: Extracting landmarks (this may take ~30s)...")
    frames_data = extract_from_folder(best)
    valid = sum(1 for f in frames_data if f["pose"] is not None)
    print(f"  Extracted {len(frames_data)} frames, {valid} with pose detected")

    if valid == 0:
        print("WARNING: No pose detected. Generating a basic static SiGML.")

    # 4. Pick a representative middle frame for static analysis
    mid_frames = [f for f in frames_data if f["pose"] is not None]
    if not mid_frames:
        mid_frames = frames_data

    # Use the middle portion for handshape analysis
    start_i = len(mid_frames) // 4
    end_i   = 3 * len(mid_frames) // 4
    key_frames = mid_frames[start_i:end_i] or mid_frames

    # 5. Determine dominant hand (most detected)
    r_count = sum(1 for f in key_frames if f["right"] is not None)
    l_count = sum(1 for f in key_frames if f["left"]  is not None)
    dom_key  = "right" if r_count >= l_count else "left"
    print(f"  Dominant hand: {dom_key}  (R={r_count}, L={l_count})")

    # 6. Analyze middle-ish frame
    best_frame = None
    for f in key_frames:
        if f[dom_key] is not None and f["pose"] is not None:
            best_frame = f
            break
    if best_frame is None:
        best_frame = key_frames[len(key_frames)//2] if key_frames else frames_data[0]

    hand_info = analyze_hand(best_frame.get(dom_key))
    pose_lms  = best_frame.get("pose")

    # 7. Build HamNoSys tags
    print("Step 4: Mapping landmarks to HamNoSys...")
    tags = []

    # --- Handshape ---
    shape_tags = handshape_tags(hand_info, best_frame.get(dom_key))
    tags += shape_tags

    # --- Extended digit direction ---
    # Decide which digit is the 'pointing' one
    is_fist_thumb_up = False
    if hand_info:
        e = hand_info["ext"]
        is_fist = "<hamfist/>" in shape_tags
        thumb_out = e["thumb"] > 0.65
        fingers_curled = sum(1 for v in [e["index"],e["middle"],e["ring"],e["pinky"]] if v < 0.5) >= 3

        if is_fist and thumb_out and fingers_curled:
            # Thumbs-up style: use thumb direction
            thumb_dir = thumb_direction_tags(best_frame.get(dom_key))
            tags += thumb_dir
            is_fist_thumb_up = "<hamextfingeru/>" in thumb_dir
        elif e["index"] > 0.65:
            # Index finger is extended — compute its direction
            if e["index"] > 0.8:
                tags.append("<hamextfingeru/>")
            else:
                tags.append("<hamextfingero/>")

    # --- Palm orientation ---
    orient_tag = palm_orientation_tag(hand_info, is_fist_thumb_up=is_fist_thumb_up)
    tags.append(orient_tag)

    # --- Location (with debug output) ---
    loc_tag = location_tag(hand_info, pose_lms, debug=True)
    tags.append(loc_tag)

    # --- Movement ---
    mov_tags = movement_tags(frames_data, dom_key)
    tags += mov_tags

    # --- Symmetry: both hands equally active ---
    if r_count > 3 and l_count > 3:
        tags.append("<hamsymmlr/>")

    print(f"  Generated tags: {' '.join(tags)}")

    # 8. Write SiGML
    print("Step 5: Writing SiGML files...")
    sigml_content = build_sigml(tags, gloss=word)

    for dest_dir in [DATA_SIGML, WEB_SIGML]:
        out_path = dest_dir / f"{word}.sigml"
        out_path.write_text(sigml_content, encoding="utf-8")
        print(f"  Written: {out_path}")

    print(f"\n✅ Done! Now:")
    print(f"   1. Make sure the server is running (python -m http.server 8000 in web-simulator/)")
    print(f"   2. Open http://localhost:8000")
    print(f"   3. Type '{word}' in the input box and click Sign")
    print(f"\nGenerated SiGML content preview:")
    print("─" * 60)
    print(sigml_content)
    print("─" * 60)

    return sigml_content


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test SiGML generation for one word")
    parser.add_argument("--sign-id", type=int, default=32,
                        help="SignID from the KArSL-502 dataset (default: 32 = 'ا')")
    parser.add_argument("--word", type=str, default="ا",
                        help="Arabic word/label to use as filename (default: ا)")
    args = parser.parse_args()
    test_one(args.sign_id, args.word)
