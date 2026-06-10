#!/usr/bin/env python3
"""
pose.py - 静止画から人物の骨格と体幹軸を推定する stdio フィルタ

依存:
    pip install mediapipe opencv-python numpy
    (Apple Silicon Mac でそのまま動く。Python は 3.12 系を推奨)

モデル:
    初回起動時に pose_landmarker.task を自動ダウンロードして
    スクリプトと同じディレクトリに保存する。

使い方 (Unix フィルタとして):
    # 標準入力で画像 → 注釈付き PNG を標準出力、解析値(JSON)を標準エラーへ
    cat photo.jpg | ./pose.py > annotated.png

    # 解析値だけ欲しい(画像出力を捨てる)場合
    cat photo.jpg | ./pose.py 2>result.json >/dev/null

    # ファイル指定でも可
    ./pose.py -i photo.jpg -o annotated.png

軸の定義:
    両肩の中点 (shoulder midpoint) と 両尻の中点 (hip midpoint) を結ぶ線を
    「体幹軸」とし、鉛直線からの傾き(度)を tilt_deg として出力する。
    画像座標は y が下向きなので、見た目どおりの傾きに直して計算している。
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
from mediapipe.framework.formats import landmark_pb2

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "pose_landmarker/pose_landmarker_heavy/float16/1/pose_landmarker_heavy.task"
)
MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "pose_landmarker.task")

# BlazePose 33点のうち、軸の計算に使うランドマーク番号
L_SHOULDER, R_SHOULDER = 11, 12
L_HIP, R_HIP = 23, 24


def log(*a):
    """ログは標準エラーに出す(標準出力は画像バイト用に空けておく)"""
    print(*a, file=sys.stderr)


def ensure_model():
    if not os.path.exists(MODEL_PATH):
        log(f"モデルが無いのでダウンロードします: {MODEL_PATH}")
        urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
        log("ダウンロード完了")


def read_image():
    """-i 指定があればファイルから、無ければ標準入力(バイナリ)から読む"""
    if args.input:
        bgr = cv2.imread(args.input)
        if bgr is None:
            log(f"画像を読めません: {args.input}")
            sys.exit(1)
        return bgr
    data = sys.stdin.buffer.read()
    if not data:
        log("標準入力に画像がありません。-i でファイル指定もできます。")
        sys.exit(1)
    buf = np.frombuffer(data, dtype=np.uint8)
    bgr = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    if bgr is None:
        log("画像をデコードできませんでした")
        sys.exit(1)
    return bgr


def detect(bgr):
    ensure_model()
    options = vision.PoseLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=MODEL_PATH),
        running_mode=vision.RunningMode.IMAGE,
        num_poses=1,
        min_pose_detection_confidence=0.5,
        output_segmentation_masks=False,
    )
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
    with vision.PoseLandmarker.create_from_options(options) as landmarker:
        return landmarker.detect(mp_image)


def draw_skeleton(bgr, landmarks):
    """公式サンプル準拠: Tasks の結果を NormalizedLandmarkList に変換して描画"""
    proto = landmark_pb2.NormalizedLandmarkList()
    proto.landmark.extend([
        landmark_pb2.NormalizedLandmark(x=lm.x, y=lm.y, z=lm.z)
        for lm in landmarks
    ])
    mp.solutions.drawing_utils.draw_landmarks(
        bgr,
        proto,
        mp.solutions.pose.POSE_CONNECTIONS,
        mp.solutions.drawing_styles.get_default_pose_landmarks_style(),
    )
    return bgr


def midpoint(landmarks, i, j):
    return np.array([(landmarks[i].x + landmarks[j].x) / 2.0,
                     (landmarks[i].y + landmarks[j].y) / 2.0])


def analyze_axis(bgr, landmarks):
    """体幹軸を描画し、傾き(度)などを返す"""
    h, w = bgr.shape[:2]
    sh = midpoint(landmarks, L_SHOULDER, R_SHOULDER)   # 肩の中点(正規化座標 0-1)
    hp = midpoint(landmarks, L_HIP, R_HIP)             # 尻の中点

    # ピクセル座標へ
    sh_px = (int(sh[0] * w), int(sh[1] * h))
    hp_px = (int(hp[0] * w), int(hp[1] * h))

    # 軸ベクトル: 尻→肩。画像 y は下向きなので符号反転して通常座標に直す
    dx = sh[0] - hp[0]
    dy = -(sh[1] - hp[1])
    # 鉛直(真上)からの傾き。0度=直立、+で右傾き
    tilt_deg = float(np.degrees(np.arctan2(dx, dy)))

    # 軸線(黄)とランドマーク点(マゼンタ)を上書き描画
    cv2.line(bgr, hp_px, sh_px, (0, 255, 255), 3)
    for p in (sh_px, hp_px):
        cv2.circle(bgr, p, 6, (255, 0, 255), -1)

    return {
        "shoulder_mid_norm": [round(float(sh[0]), 4), round(float(sh[1]), 4)],
        "hip_mid_norm": [round(float(hp[0]), 4), round(float(hp[1]), 4)],
        "trunk_tilt_deg_from_vertical": round(tilt_deg, 2),
        "note": "0=直立, 正=肩が右に傾く。単眼推定なので前後の傾きは含まない",
    }


def main():
    bgr = read_image()
    result = detect(bgr)

    if not result.pose_landmarks:
        log("人物を検出できませんでした")
        # 解析値は空で返す
        sys.stderr.write(json.dumps({"detected": False}, ensure_ascii=False) + "\n")
        sys.exit(2)

    landmarks = result.pose_landmarks[0]
    annotated = draw_skeleton(bgr, landmarks)
    analysis = analyze_axis(annotated, landmarks)

    # 3D ワールド座標(肩・尻の中点)も参考値として付ける
    if result.pose_world_landmarks:
        wl = result.pose_world_landmarks[0]
        analysis["world_shoulder_mid_m"] = [
            round((wl[L_SHOULDER].x + wl[R_SHOULDER].x) / 2, 3),
            round((wl[L_SHOULDER].y + wl[R_SHOULDER].y) / 2, 3),
            round((wl[L_SHOULDER].z + wl[R_SHOULDER].z) / 2, 3),
        ]

    analysis["detected"] = True

    # 解析値(JSON)は標準エラーへ
    sys.stderr.write(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n")

    # 注釈付き画像(PNG バイト)は標準出力へ。-o 指定があればファイルにも保存
    ok, png = cv2.imencode(".png", annotated)
    if not ok:
        log("画像エンコードに失敗")
        sys.exit(1)
    if args.output:
        cv2.imwrite(args.output, annotated)
        log(f"保存しました: {args.output}")
    # パイプ先がある時だけ標準出力へ流す
    if not sys.stdout.isatty():
        sys.stdout.buffer.write(png.tobytes())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="静止画から骨格と体幹軸を推定")
    parser.add_argument("-i", "--input", help="入力画像パス(省略時は標準入力)")
    parser.add_argument("-o", "--output", help="注釈付き画像の保存先パス")
    args = parser.parse_args()
    main()
