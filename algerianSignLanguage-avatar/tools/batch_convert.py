# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

"""
Batch Convert KArSL-502 videos to SiGML animations for the Algerian Sign Language avatar.
"""

import os
import re
import math
import argparse
import urllib.request
import json
import shutil
from pathlib import Path
import pandas as pd
import numpy as np
from tqdm import tqdm
import cv2
import mediapipe as mp

# ── Paths ────────────────────────────────────────────────────────────────────
SCRIPT_DIR   = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
DATA_SIGML   = PROJECT_ROOT / "data" / "sigml"
WEB_SIGML    = PROJECT_ROOT / "web-simulator" / "sigml"
MODEL_DIR    = SCRIPT_DIR / "models"
DATASET_ROOT = Path(r"E:\Graduation project\KArSL-502\01\test")
LABELS_PATH  = Path(r"E:\Graduation project\old\KARSL-502_Labels.xlsx")

MODEL_DIR.mkdir(parents=True, exist_ok=True)
DATA_SIGML.mkdir(parents=True, exist_ok=True)
WEB_SIGML.mkdir(parents=True, exist_ok=True)

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
            print(f"Downloading {path.name}...")
            urllib.request.urlretrieve(url, path)

def sort_key(p: Path) -> int:
    m = re.search(r'(\d+)$', p.stem)
    return int(m.group()) if m else 0

def extract_from_folder(folder: Path, pose_lmk, hand_lmk):
    frames = sorted(folder.glob("*.jpg"), key=sort_key)
    results = []

    for i, fp in enumerate(frames):
        img = cv2.imread(str(fp))
        if img is None:
            continue
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

        pose_r = pose_lmk.detect(mp_img)
        hand_r = hand_lmk.detect(mp_img)

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

def pick_best_clip(word_folder: Path) -> Path:
    best_folder, best_score = None, -1
    for sub in sorted(word_folder.iterdir()):
        if not sub.is_dir():
            continue
        imgs = list(sub.glob("*.jpg"))
        if not imgs:
            continue
        score = len(imgs)
        if score > best_score:
            best_score = score
            best_folder = sub
    return best_folder

def pt(lms, idx):
    l = lms[idx]
    return np.array([l.x, l.y, l.z])

def dist(a, b):
    return float(np.linalg.norm(a - b))

def finger_curl(lms, tip_i, dip_i, pip_i, mcp_i, wrist_i=0):
    wrist = pt(lms, wrist_i)
    mcp   = pt(lms, mcp_i)
    tip   = pt(lms, tip_i)
    d_mcp = dist(wrist, mcp)
    if d_mcp < 1e-6:
        return 0.5
    return min(dist(wrist, tip) / (d_mcp * 2.2), 1.0)

def analyze_hand(lms):
    if lms is None:
        return None

    wrist = pt(lms, 0)
    index  = finger_curl(lms, 8,  7,  6,  5)
    middle = finger_curl(lms, 12, 11, 10, 9)
    ring   = finger_curl(lms, 16, 15, 14, 13)
    pinky  = finger_curl(lms, 20, 19, 18, 17)
    thumb  = finger_curl(lms, 4,  3,  2,  1)

    thumb_tip = pt(lms, 4)
    index_tip = pt(lms, 8)
    hand_size = dist(wrist, pt(lms, 9))
    pinch_dist = dist(thumb_tip, index_tip) / (hand_size + 1e-6)

    v1 = pt(lms, 5)  - pt(lms, 0)
    v2 = pt(lms, 17) - pt(lms, 0)
    normal = np.cross(v1, v2)
    norm_len = np.linalg.norm(normal)
    if norm_len > 1e-6:
        normal = normal / norm_len

    return {
        "ext": {"index": index, "middle": middle, "ring": ring,
                "pinky": pinky, "thumb": thumb},
        "pinch_dist": pinch_dist,
        "normal": normal,
        "wrist": wrist,
    }

def thumb_direction_tags(lms):
    if lms is None:
        return []
    tip = pt(lms, 4)
    mcp = pt(lms, 2)
    vec = tip - mcp
    norm = np.linalg.norm(vec)
    if norm < 1e-6:
        return []
    vec = vec / norm
    tx, ty = float(vec[0]), float(vec[1])
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
    if h is None:
        return ["<hamfist/>"]

    e = h["ext"]
    pd = h["pinch_dist"]

    num_ext  = sum(1 for v in [e["index"], e["middle"], e["ring"], e["pinky"]] if v > 0.72)
    num_curl = sum(1 for v in [e["index"], e["middle"], e["ring"], e["pinky"]] if v < 0.45)
    thumb_out = e["thumb"] > 0.65

    if pd < 0.18:
        return ["<hampinchall/>", "<hamfingerstraightmod/>"]

    if num_curl >= 3:
        tags = ["<hamfist/>"]
        if thumb_out:
            tags.append("<hamthumboutmod/>")
        return tags

    if num_ext >= 4:
        tags = ["<hamfinger2345/>"]
        if thumb_out:
            tags.append("<hamthumbopenmod/>")
        return tags

    if e["index"] > 0.72 and e["middle"] < 0.5 and e["ring"] < 0.5 and e["pinky"] < 0.5:
        return ["<hamfinger2/>"]

    if e["index"] > 0.72 and e["middle"] > 0.72 and e["ring"] < 0.5 and e["pinky"] < 0.5:
        return ["<hamfinger23/>"]

    if e["index"] > 0.72 and e["middle"] > 0.72 and e["ring"] > 0.72 and e["pinky"] < 0.5:
        return ["<hamfinger234/>"]

    return ["<hamfinger2345/>"]

def palm_orientation_tag(h, is_fist_thumb_up=False):
    if h is None:
        return "<hampalmu/>"

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

LOCATION_MAP = [
    (0.10, "<hamforehead/>"),
    (0.22, "<hamlips/>"),
    (0.35, "<hamchin/>"),
    (0.50, "<hamchest/>"),
    (0.70, "<hamstomach/>"),
    (1.00, "<hamneutralspace/>"),
]

def location_tag(hand_info, pose_lms):
    if hand_info is None or pose_lms is None:
        return "<hamneutralspace/>"

    nose_y      = pose_lms[0].y
    l_sh_y      = pose_lms[11].y
    r_sh_y      = pose_lms[12].y
    shoulder_y  = (l_sh_y + r_sh_y) / 2.0
    l_hip_y     = pose_lms[23].y
    r_hip_y     = pose_lms[24].y
    hip_y       = (l_hip_y + r_hip_y) / 2.0

    shoulder_z  = (pose_lms[11].z + pose_lms[12].z) / 2.0
    wrist_z     = float(hand_info["wrist"][2])
    wrist_y     = float(hand_info["wrist"][1])

    torso_h     = max(hip_y - shoulder_y, 0.01)
    z_forward   = shoulder_z - wrist_z

    if z_forward > 0.08:
        if wrist_y < shoulder_y - 0.04:
            if wrist_y < nose_y:
                return "<hamforehead/>"
            return "<hamlips/>"
        elif wrist_y < shoulder_y + torso_h * 0.4:
            return "<hamneutralspace/>"
        else:
            return "<hamneutralspace/>"

    dy = wrist_y - shoulder_y

    if dy < -(torso_h * 0.3):
        if wrist_y < nose_y - 0.02:
            return "<hamforehead/>"
        elif wrist_y < nose_y + 0.04:
            return "<hamnose/>"
        else:
            return "<hamlips/>"
    elif dy < 0:
        return "<hamshouldertop/>"
    elif dy < torso_h * 0.35:
        return "<hamchest/>"
    elif dy < torso_h * 0.75:
        return "<hamstomach/>"
    else:
        return "<hamneutralspace/>"

def movement_tags(frames_data, hand_key="right"):
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

    if magnitude < 0.04:
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

def main():
    parser = argparse.ArgumentParser(description="Batch convert KArSL dataset to SiGML")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of processed words")
    args = parser.parse_args()

    print("Checking MediaPipe models...")
    ensure_models()

    print(f"Reading labels from {LABELS_PATH}...")
    df = pd.read_excel(LABELS_PATH)
    # Clean the Sign-Arabic text to create clean gloss strings
    df['gloss'] = df['Sign-Arabic'].astype(str).str.split('/').str[0].str.strip()
    # Filter out numeric only entries (like counts 0-1000)
    df = df[~df['gloss'].str.replace('.','').str.replace('-','').str.isdigit()]

    if args.limit:
        df = df.head(args.limit)

    total_words = len(df)
    print(f"Found {total_words} KArSL sign words to convert.")

    # Load categories file so we can update it
    cat_file_path = PROJECT_ROOT / "data" / "categories_files.json"
    if cat_file_path.exists():
        with open(cat_file_path, encoding='utf-8') as f:
            categories = json.load(f)
    else:
        categories = {}

    karsl_cat = "KArSL-502"
    if karsl_cat not in categories:
        categories[karsl_cat] = []

    # Initialize MediaPipe Task instances once for reuse across batch
    from mediapipe.tasks.python.core import base_options as _bo
    from mediapipe.tasks.python.vision import (
        PoseLandmarker, PoseLandmarkerOptions,
        HandLandmarker, HandLandmarkerOptions,
        RunningMode,
    )

    pose_opts = PoseLandmarkerOptions(
        base_options=_bo.BaseOptions(model_asset_path=str(POSE_MODEL)),
        running_mode=RunningMode.IMAGE,
        num_poses=1,
        min_pose_detection_confidence=0.4,
        min_pose_presence_confidence=0.4,
    )
    hand_opts = HandLandmarkerOptions(
        base_options=_bo.BaseOptions(model_asset_path=str(HAND_MODEL)),
        running_mode=RunningMode.IMAGE,
        num_hands=2,
        min_hand_detection_confidence=0.4,
        min_hand_presence_confidence=0.4,
    )

    success_count = 0
    skipped_count = 0
    error_count = 0

    print("Initializing MediaPipe models and starting processing...")
    with (PoseLandmarker.create_from_options(pose_opts) as pose_lmk,
          HandLandmarker.create_from_options(hand_opts) as hand_lmk):

        for idx, row in tqdm(enumerate(df.iterrows(), 1), total=total_words, desc="Converting signs"):
            _, data = row
            sign_id = int(data['SignID'])
            gloss   = str(data['gloss'])

            # Clean name for safe filename
            safe_gloss = re.sub(r'[\\/*?:"<>|]', "", gloss).strip()
            if not safe_gloss:
                skipped_count += 1
                continue

            word_folder = DATASET_ROOT / f"{sign_id:04d}"
            if not word_folder.exists():
                skipped_count += 1
                continue

            best_clip_folder = pick_best_clip(word_folder)
            if not best_clip_folder:
                skipped_count += 1
                continue

            try:
                frames_data = extract_from_folder(best_clip_folder, pose_lmk, hand_lmk)
                valid_frames = [f for f in frames_data if f["pose"] is not None]

                if not valid_frames:
                    # Basic fallback if no pose detected
                    tags = ["<hamfist/>", "<hamextfingeru/>", "<hampalml/>", "<hamchest/>"]
                else:
                    mid_frames = valid_frames
                    start_i = len(mid_frames) // 4
                    end_i   = 3 * len(mid_frames) // 4
                    key_frames = mid_frames[start_i:end_i] or mid_frames

                    r_count = sum(1 for f in key_frames if f["right"] is not None)
                    l_count = sum(1 for f in key_frames if f["left"]  is not None)
                    dom_key  = "right" if r_count >= l_count else "left"

                    best_frame = None
                    for f in key_frames:
                        if f[dom_key] is not None:
                            best_frame = f
                            break
                    if best_frame is None:
                        best_frame = key_frames[len(key_frames)//2]

                    hand_info = analyze_hand(best_frame.get(dom_key))
                    pose_lms  = best_frame.get("pose")

                    tags = []
                    shape_tags = handshape_tags(hand_info, best_frame.get(dom_key))
                    tags += shape_tags

                    is_fist_thumb_up = False
                    if hand_info:
                        e = hand_info["ext"]
                        is_fist = "<hamfist/>" in shape_tags
                        thumb_out = e["thumb"] > 0.65
                        fingers_curled = sum(1 for v in [e["index"],e["middle"],e["ring"],e["pinky"]] if v < 0.5) >= 3

                        if is_fist and thumb_out and fingers_curled:
                            thumb_dir = thumb_direction_tags(best_frame.get(dom_key))
                            tags += thumb_dir
                            is_fist_thumb_up = "<hamextfingeru/>" in thumb_dir
                        elif e["index"] > 0.65:
                            if e["index"] > 0.8:
                                tags.append("<hamextfingeru/>")
                            else:
                                tags.append("<hamextfingero/>")

                    orient_tag = palm_orientation_tag(hand_info, is_fist_thumb_up=is_fist_thumb_up)
                    tags.append(orient_tag)

                    loc_tag = location_tag(hand_info, pose_lms)
                    tags.append(loc_tag)

                    mov_tags = movement_tags(frames_data, dom_key)
                    tags += mov_tags

                    if r_count > 3 and l_count > 3:
                        tags.append("<hamsymmlr/>")

                sigml_content = build_sigml(tags, gloss=safe_gloss)

                # Write files
                (DATA_SIGML / f"{safe_gloss}.sigml").write_text(sigml_content, encoding="utf-8")
                (WEB_SIGML / f"{safe_gloss}.sigml").write_text(sigml_content, encoding="utf-8")

                if safe_gloss not in categories[karsl_cat]:
                    categories[karsl_cat].append(safe_gloss)

                success_count += 1

            except Exception as e:
                import traceback
                print(f"Error converting SignID {sign_id}: {e}")
                traceback.print_exc()
                error_count += 1

    # Save categories files
    with open(cat_file_path, 'w', encoding='utf-8') as f:
        json.dump(categories, f, ensure_ascii=False, indent=4)
    shutil.copy(str(cat_file_path), str(PROJECT_ROOT / "web-simulator" / "categories_files.json"))

    print("\n" + "="*50)
    print("Batch Conversion Complete!")
    print(f"Successfully converted: {success_count} words")
    print(f"Skipped (missing/empty): {skipped_count} words")
    print(f"Errors occurred: {error_count} words")
    print(f"Categories file updated: {cat_file_path}")
    print("="*50)

if __name__ == "__main__":
    main()
