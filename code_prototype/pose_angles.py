#!/usr/bin/env python3
"""
pose_angles.py - 静止画から関節角度を抽出して JSON で出すフィルタ

依存:
    pip install mediapipe opencv-python numpy

使い方:
    ./pose_angles.py -i teacher.jpg > teacher.json
    cat performer1.jpg | ./pose_angles.py > performer1.json
    # 注釈付き画像も欲しいとき
    ./pose_angles.py -i performer1.jpg -o performer1_annotated.png > performer1.json

出力JSON:
    detected     : 人物を検出できたか
    image_size   : [幅, 高さ] (px)
    angles       : 関節角度(度)。下記 JOINTS の各キー
    visibility   : 各関節の信頼度(0-1, 3点の最小値)。低いと角度が当てにならない
    trunk_tilt   : 体幹軸の鉛直からの傾き(度, 0=直立)
    landmarks    : 正規化座標 {番号: [x, y, visibility]} (重ね描き用)

注意:
    ここで出す角度は「カメラに写った2D投影面での角度」。
    奥行き方向の情報は含まないので、比較する写真は撮影角度・距離を
    揃えること(全演者を同じ向き・同じ距離で撮る)が前提。
"""

import sys
import os
import json
import argparse
import urllib.request

import numpy as np
import cv2
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "pose_landmarker/pose_landmarker_heavy/float16/1/pose_landmarker_heavy.task"
)
MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "pose_landmarker.task")

# BlazePose 33点の番号
NOSE = 0
L_SH, R_SH = 11, 12          # shoulder
L_EL, R_EL = 13, 14          # elbow
L_WR, R_WR = 15, 16          # wrist
L_HP, R_HP = 23, 24          # hip
L_KN, R_KN = 25, 26          # knee
L_AN, R_AN = 27, 28          # ankle

# 角度を測る関節: 名前 -> (端A, 頂点B, 端C)。Bを挟む角度を測る
JOINTS = {
    "left_elbow":     (L_SH, L_EL, L_WR),
    "right_elbow":    (R_SH, R_EL, R_WR),
    "left_shoulder":  (L_EL, L_SH, L_HP),
    "right_shoulder": (R_EL, R_SH, R_HP),
    "left_hip":       (L_SH, L_HP, L_KN),
    "right_hip":      (R_SH, R_HP, R_KN),
    "left_knee":      (L_HP, L_KN, L_AN),
    "right_knee":     (R_HP, R_KN, R_AN),
}

# 重ね描きに使う骨格の辺
EDGES = [(L_SH, R_SH), (L_SH, L_HP), (R_SH, R_HP), (L_HP, R_HP),
         (L_SH, L_EL), (L_EL, L_WR), (R_SH, R_EL), (R_EL, R_WR),
         (L_HP, L_KN), (L_KN, L_AN), (R_HP, R_KN), (R_KN, R_AN)]


def log(*a):
    print(*a, file=sys.stderr)


def ensure_model():
    if not os.path.exists(MODEL_PATH):
        log(f"モデルをダウンロード中: {MODEL_PATH}")
        urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
        log("完了")


def read_image(path):
    if path:
        bgr = cv2.imread(path)
        if bgr is None:
            log(f"画像を読めません: {path}")
            sys.exit(1)
        return bgr
    data = sys.stdin.buffer.read()
    if not data:
        log("標準入力に画像がありません。-i でファイル指定も可。")
        sys.exit(1)
    bgr = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if bgr is None:
        log("画像をデコードできません")
        sys.exit(1)
    return bgr


def detect(bgr):
    ensure_model()
    options = vision.PoseLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=MODEL_PATH),
        running_mode=vision.RunningMode.IMAGE,
        num_poses=1,
        min_pose_detection_confidence=0.5,
    )
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
    with vision.PoseLandmarker.create_from_options(options) as lm:
        return lm.detect(mp_image)


def to_px(lm, i, w, h):
    """正規化座標(0-1)をピクセル座標へ。x,y で実寸スケールが違うので必ず変換する"""
    return np.array([lm[i].x * w, lm[i].y * h])


def angle_at(lm, a, b, c, w, h):
    """頂点 b を挟む角度(度)。2本のベクトルの内積から arccos"""
    A = to_px(lm, a, w, h)
    B = to_px(lm, b, w, h)
    C = to_px(lm, c, w, h)
    v1, v2 = A - B, C - B
    n1, n2 = np.linalg.norm(v1), np.linalg.norm(v2)
    if n1 == 0 or n2 == 0:
        return None
    cosv = np.clip(np.dot(v1, v2) / (n1 * n2), -1.0, 1.0)
    return float(np.degrees(np.arccos(cosv)))


def trunk_tilt(lm, w, h):
    sh = (to_px(lm, L_SH, w, h) + to_px(lm, R_SH, w, h)) / 2
    hp = (to_px(lm, L_HP, w, h) + to_px(lm, R_HP, w, h)) / 2
    dx = sh[0] - hp[0]
    dy = -(sh[1] - hp[1])      # 画像yは下向きなので反転
    return float(np.degrees(np.arctan2(dx, dy)))


def draw(bgr, lm):
    h, w = bgr.shape[:2]
    for a, b in EDGES:
        pa = tuple(to_px(lm, a, w, h).astype(int))
        pb = tuple(to_px(lm, b, w, h).astype(int))
        cv2.line(bgr, pa, pb, (0, 200, 0), 2)
    for i in range(33):
        cv2.circle(bgr, tuple(to_px(lm, i, w, h).astype(int)), 3, (255, 0, 255), -1)
    return bgr


def main():
    bgr = read_image(args.input)
    h, w = bgr.shape[:2]
    res = detect(bgr)

    if not res.pose_landmarks:
        sys.stdout.write(json.dumps({"detected": False}, ensure_ascii=False) + "\n")
        log("人物を検出できませんでした")
        sys.exit(2)

    lm = res.pose_landmarks[0]

    angles, visibility = {}, {}
    for name, (a, b, c) in JOINTS.items():
        angles[name] = angle_at(lm, a, b, c, w, h)
        # 3点の visibility の最小値を信頼度とする
        visibility[name] = round(min(lm[a].visibility, lm[b].visibility,
                                      lm[c].visibility), 3)

    out = {
        "detected": True,
        "source": args.input or "stdin",
        "image_size": [w, h],
        "angles": {k: (round(v, 2) if v is not None else None)
                   for k, v in angles.items()},
        "visibility": visibility,
        "trunk_tilt_deg": round(trunk_tilt(lm, w, h), 2),
        "landmarks": {str(i): [round(lm[i].x, 5), round(lm[i].y, 5),
                               round(lm[i].visibility, 3)] for i in range(33)},
    }

    if args.output:
        cv2.imwrite(args.output, draw(bgr, lm))
        log(f"注釈付き画像を保存: {args.output}")

    sys.stdout.write(json.dumps(out, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="静止画から関節角度を抽出")
    p.add_argument("-i", "--input", help="入力画像(省略時は標準入力)")
    p.add_argument("-o", "--output", help="注釈付き画像の保存先")
    args = p.parse_args()
    main()
