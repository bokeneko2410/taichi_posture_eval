#!/usr/bin/env python3
"""
taichi_record.py - 太極拳姿勢評価: データ取得プログラム (Phase 1)

写真1枚と撮影メタ情報から指標の生値を測定し、measurements.jsonl に
追記保存する。判定エンジンは別段階(墜肘のみA基準の判定を付与)。
仕様書 v1.2 §5.2 レコード形式 / §8 ディレクトリ構造に準拠。

依存:
    pip install mediapipe opencv-python numpy

使い方:
    # キーポーズの記録(演者ID・ポーズID・方向は必須)
    ./taichi_record.py -i photo.jpg --performer p001 \
        --pose loushi_aobu --direction side

    # セッション冒頭のキャリブレーション
    ./taichi_record.py -i yubei_front.jpg --performer p001 \
        --pose baseline --direction front
    ./taichi_record.py -i shrug.jpg --performer p001 \
        --pose baseline_shrug --direction front

    # 数学部分のセルフテスト(MediaPipe不要)
    ./taichi_record.py --selftest

    # 集計例(awk): p001 の右肘めくれ角の推移
    awk -F'"' '/p001/ && /elbow_flare_deg_r/' data/measurements.jsonl

出力:
    data/measurements.jsonl                       追記専用の測定レコード
    data/performers/<id>/sessions/<session>/<pose>/   元写真コピー＋抽出結果
"""

import sys
import os
import json
import math
import shutil
import argparse
import datetime
import urllib.request

import numpy as np

SCHEMA_VERSION = "1.0"
EXTRACTOR_VERSION = "mediapipe-pose-landmarker-heavy/1"
THRESHOLD_SET_VERSION = "v1"
DATA_DIR = os.environ.get("TAICHI_DATA_DIR", "data")

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "pose_landmarker/pose_landmarker_heavy/float16/1/pose_landmarker_heavy.task"
)

# BlazePose 33点
NOSE = 0
L_EAR, R_EAR = 7, 8
L_SH, R_SH = 11, 12
L_EL, R_EL = 13, 14
L_WR, R_WR = 15, 16
L_HP, R_HP = 23, 24
L_KN, R_KN = 25, 26
L_AN, R_AN = 27, 28

VIS_MIN = 0.5            # これ未満のランドマークを含む指標は unmeasurable
ELBOW_STRAIGHT_DEG = 160 # 肘角がこれ超なら墜肘は原理的に測定不能

# 墜肘の閾値 (thresholds/v1.json があればそちらを優先)
DEFAULT_THRESHOLDS = {
    "elbow_flare_deg": {"ok_max": 45, "caution_max": 70},
}


def log(*a):
    print(*a, file=sys.stderr)


# ---------------------------------------------------------------
# 幾何計算 (MediaPipe 非依存。lm は {index: (x, y, visibility)} の辞書、
# x, y はピクセル座標)
# ---------------------------------------------------------------

def pt(lm, i):
    return np.array(lm[i][:2], dtype=float)


def vis(lm, *idx):
    return min(lm[i][2] for i in idx)


def angle_at(lm, a, b, c):
    """頂点 b を挟む角度(度)"""
    v1, v2 = pt(lm, a) - pt(lm, b), pt(lm, c) - pt(lm, b)
    n1, n2 = np.linalg.norm(v1), np.linalg.norm(v2)
    if n1 == 0 or n2 == 0:
        return None
    cosv = np.clip(np.dot(v1, v2) / (n1 * n2), -1.0, 1.0)
    return float(np.degrees(np.arccos(cosv)))


def trunk_len(lm):
    sh = (pt(lm, L_SH) + pt(lm, R_SH)) / 2
    hp = (pt(lm, L_HP) + pt(lm, R_HP)) / 2
    return float(np.linalg.norm(sh - hp)), sh, hp


def trunk_tilt_deg(lm):
    """体幹軸の鉛直からの傾き。画像yは下向きなので反転。正=画像上で右へ傾く"""
    _, sh, hp = trunk_len(lm)
    dx = sh[0] - hp[0]
    dy = -(sh[1] - hp[1])
    return float(np.degrees(np.arctan2(dx, dy)))


def elbow_flare_deg(lm, side):
    """墜肘: 肘頭向き(肩・手首への角二等分線の逆)の鉛直下向きからの角度。
    正=正中線から離れる向き(めくれ)。腕がほぼ伸びていれば None(測定不能)。
    戻り値: (角度 or None, 肘角度)"""
    s, e, w = (L_SH, L_EL, L_WR) if side == "l" else (R_SH, R_EL, R_WR)
    bend = angle_at(lm, s, e, w)
    if bend is None or bend > ELBOW_STRAIGHT_DEG:
        return None, bend
    u1 = pt(lm, s) - pt(lm, e)
    u2 = pt(lm, w) - pt(lm, e)
    u1 /= np.linalg.norm(u1)
    u2 /= np.linalg.norm(u2)
    inner = u1 + u2                  # 内側二等分線
    n = np.linalg.norm(inner)
    if n < 1e-9:
        return None, bend
    tip = -inner / n                 # 肘頭の向き
    # 鉛直下向き(画像座標では +y)との成す角
    ang = float(np.degrees(np.arccos(np.clip(tip[1], -1.0, 1.0))))
    # 符号: 体の正中線(尻中点x)から離れる横向き成分を正とする
    _, _, hp = trunk_len(lm)
    elbow_x = pt(lm, e)[0]
    outward = 1.0 if (elbow_x - hp[0]) * tip[0] > 0 else -1.0
    return outward * ang, bend


def shrug_raw(lm, side):
    """沈肩の生値: 肩-耳間距離 / 体幹長 (小さいほどすくんでいる)"""
    ear, sh = (L_EAR, L_SH) if side == "l" else (R_EAR, R_SH)
    tl, _, _ = trunk_len(lm)
    if tl == 0:
        return None
    return float(np.linalg.norm(pt(lm, ear) - pt(lm, sh)) / tl)


def weight_ratio(lm):
    """虚実分明の生値: 尻中点の両足首間に対する位置比 (0=左足首側, 1=右足首側。
    側面撮影では 0=画像左の足側)"""
    a, b = pt(lm, L_AN), pt(lm, R_AN)
    _, _, hp = trunk_len(lm)
    span = b[0] - a[0]
    if abs(span) < 1e-6:
        return None
    return float((hp[0] - a[0]) / span)


def stance_ratio(lm):
    """歩幅の生値: 足首間距離 / 体幹長"""
    tl, _, _ = trunk_len(lm)
    if tl == 0:
        return None
    return float(np.linalg.norm(pt(lm, L_AN) - pt(lm, R_AN)) / tl)


def head_forward_raw(lm, side):
    """虚領頂勁の生値: 耳の肩に対する前方偏位 / 体幹長 (側面用、符号は画像x正方向)"""
    ear, sh = (L_EAR, L_SH) if side == "l" else (R_EAR, R_SH)
    tl, _, _ = trunk_len(lm)
    if tl == 0:
        return None
    return float((pt(lm, ear)[0] - pt(lm, sh)[0]) / tl)


# ---------------------------------------------------------------
# 指標の定義: (metric_id, eval_type, 必要ランドマーク, 計算関数)
# ---------------------------------------------------------------

def build_metrics(lm):
    """全指標を計算し、レコード断片のリストを返す"""
    out = []

    def add(metric_id, eval_type, needed, value, judgment=None, reason=None):
        v = vis(lm, *needed)
        if v < VIS_MIN:
            out.append(dict(metric_id=metric_id, eval_type=eval_type,
                            value_raw=None, confidence=round(v, 3),
                            unmeasurable=True, reason="low_visibility"))
        elif value is None:
            out.append(dict(metric_id=metric_id, eval_type=eval_type,
                            value_raw=None, confidence=round(v, 3),
                            unmeasurable=True,
                            reason=reason or "not_computable"))
        else:
            out.append(dict(metric_id=metric_id, eval_type=eval_type,
                            value_raw=round(value, 3),
                            confidence=round(v, 3),
                            unmeasurable=False, judgment=judgment))

    th = load_thresholds()["elbow_flare_deg"]

    # A: 体幹傾き
    add("trunk_tilt_deg", "A", [L_SH, R_SH, L_HP, R_HP], trunk_tilt_deg(lm))

    # A: 墜肘(左右)
    for side in ("l", "r"):
        flare, bend = elbow_flare_deg(lm, side)
        s, e, w = (L_SH, L_EL, L_WR) if side == "l" else (R_SH, R_EL, R_WR)
        if flare is None and bend is not None and bend > ELBOW_STRAIGHT_DEG:
            add(f"elbow_flare_deg_{side}", "A", [s, e, w], None,
                reason="arm_straight")
        else:
            judg = None
            if flare is not None:
                a = abs(flare)
                judg = ("OK" if a <= th["ok_max"]
                        else "caution" if a <= th["caution_max"]
                        else "fix")
            add(f"elbow_flare_deg_{side}", "A", [s, e, w], flare,
                judgment=judg)
        # 肘角度の生値(B用)も記録
        add(f"elbow_bend_deg_{side}", "B", [s, e, w], bend)

    # B: 膝角度(左右)
    add("knee_bend_deg_l", "B", [L_HP, L_KN, L_AN],
        angle_at(lm, L_HP, L_KN, L_AN))
    add("knee_bend_deg_r", "B", [R_HP, R_KN, R_AN],
        angle_at(lm, R_HP, R_KN, R_AN))

    # B: 重心位置比・歩幅比
    add("weight_ratio", "B", [L_AN, R_AN, L_SH, R_SH, L_HP, R_HP],
        weight_ratio(lm))
    add("stance_ratio", "B", [L_AN, R_AN, L_SH, R_SH, L_HP, R_HP],
        stance_ratio(lm))

    # C: 沈肩の生値(左右)・頭部前方偏位(左右)
    add("shrug_raw_l", "C", [L_EAR, L_SH, R_SH, L_HP, R_HP], shrug_raw(lm, "l"))
    add("shrug_raw_r", "C", [R_EAR, L_SH, R_SH, L_HP, R_HP], shrug_raw(lm, "r"))
    add("head_fwd_raw_l", "C", [L_EAR, L_SH, R_SH, L_HP, R_HP],
        head_forward_raw(lm, "l"))
    add("head_fwd_raw_r", "C", [R_EAR, L_SH, R_SH, L_HP, R_HP],
        head_forward_raw(lm, "r"))

    return out


# ---------------------------------------------------------------
# 閾値・入出力
# ---------------------------------------------------------------

def load_thresholds():
    path = os.path.join(DATA_DIR, "thresholds",
                        f"{THRESHOLD_SET_VERSION}.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return DEFAULT_THRESHOLDS


def detect_landmarks(image_path):
    """MediaPipe で抽出し {index: (x_px, y_px, visibility)} と画像サイズを返す"""
    import cv2
    import mediapipe as mp
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision

    model_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "pose_landmarker.task")
    if not os.path.exists(model_path):
        log("モデルをダウンロード中...")
        urllib.request.urlretrieve(MODEL_URL, model_path)

    bgr = cv2.imread(image_path)
    if bgr is None:
        sys.exit(f"画像を読めません: {image_path}")
    h, w = bgr.shape[:2]
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)

    options = vision.PoseLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=model_path),
        running_mode=vision.RunningMode.IMAGE,
        num_poses=1,
        min_pose_detection_confidence=0.5,
    )
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
    with vision.PoseLandmarker.create_from_options(options) as plm:
        res = plm.detect(mp_image)
    if not res.pose_landmarks:
        sys.exit("人物を検出できませんでした(レコードは追記しません)")
    raw = res.pose_landmarks[0]
    lm = {i: (raw[i].x * w, raw[i].y * h, raw[i].visibility)
          for i in range(33)}
    return lm, (w, h)


def append_records(records):
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, "measurements.jsonl")
    with open(path, "a", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return path


def store_session_files(image_path, lm, size, meta):
    """元写真と抽出結果をセッションディレクトリへ保存し、相対パスを返す"""
    d = os.path.join(DATA_DIR, "performers", meta["performer_id"],
                     "sessions", meta["session_id"], meta["pose_id"])
    os.makedirs(d, exist_ok=True)
    stamp = meta["timestamp"].replace(":", "").replace("-", "")[:15]
    base = f"{meta['direction']}_{stamp}"
    img_dst = os.path.join(d, base + os.path.splitext(image_path)[1].lower())
    shutil.copy2(image_path, img_dst)
    with open(os.path.join(d, base + "_landmarks.json"), "w",
              encoding="utf-8") as f:
        json.dump({"image_size": size,
                   "extractor_version": EXTRACTOR_VERSION,
                   "landmarks_px": {str(i): [round(v, 2) for v in lm[i]]
                                    for i in lm}},
                  f, ensure_ascii=False)
    return os.path.relpath(img_dst, DATA_DIR)


# ---------------------------------------------------------------
# セルフテスト(合成ランドマーク、MediaPipe不要)
# ---------------------------------------------------------------

def selftest():
    def make_upright():
        """直立・腕を曲げて肘がほぼ真下を向く合成ポーズ"""
        lm = {}
        for i in range(33):
            lm[i] = (0.0, 0.0, 0.9)
        lm[L_EAR] = (480, 95, 0.9);  lm[R_EAR] = (520, 95, 0.9)
        lm[L_SH] = (450, 200, 0.9); lm[R_SH] = (550, 200, 0.9)
        lm[L_HP] = (470, 450, 0.9); lm[R_HP] = (530, 450, 0.9)
        lm[L_AN] = (465, 800, 0.9); lm[R_AN] = (535, 800, 0.9)
        lm[L_KN] = (467, 620, 0.9); lm[R_KN] = (533, 620, 0.9)
        # 左腕: 肘を体側で曲げ、手首を前上方に。肘頭はほぼ真下を向くはず
        lm[L_EL] = (430, 330, 0.9); lm[L_WR] = (430, 210, 0.9)
        # 右腕: 肘を横に張り上げる(めくれ状態)。手首は肘の内側下方
        lm[R_EL] = (650, 200, 0.9); lm[R_WR] = (640, 320, 0.9)
        return lm

    lm = make_upright()
    ok = True

    t = trunk_tilt_deg(lm)
    ok &= abs(t) < 1.0
    print(f"trunk_tilt 直立 ≈0: {t:.2f} deg ... {'OK' if abs(t)<1 else 'NG'}")

    fl, bend_l = elbow_flare_deg(lm, "l")
    # 左肘: 肩が真上(450,200)→ずれ20px, 手首ほぼ真上 → 肘頭はほぼ真下
    print(f"左肘 flare(下向き期待): {fl:.1f} deg (bend {bend_l:.0f}) ... "
          f"{'OK' if abs(fl) < 25 else 'NG'}")
    ok &= abs(fl) < 25

    fr, bend_r = elbow_flare_deg(lm, "r")
    # 右肘: 横に張った状態 → 大きな外向き角(>45)を期待
    print(f"右肘 flare(めくれ期待 >45): {fr:.1f} deg (bend {bend_r:.0f}) ... "
          f"{'OK' if fr > 45 else 'NG'}")
    ok &= fr > 45

    # 腕を伸ばすと測定不能になるか
    lm2 = dict(lm)
    lm2[L_EL] = (440, 330, 0.9); lm2[L_WR] = (430, 460, 0.9)  # ほぼ一直線
    fs, bend_s = elbow_flare_deg(lm2, "l")
    print(f"伸ばした腕: flare={fs} (bend {bend_s:.0f}) ... "
          f"{'OK' if fs is None else 'NG'}")
    ok &= fs is None

    wr = weight_ratio(lm)
    print(f"weight_ratio 中央 ≈0.5: {wr:.3f} ... "
          f"{'OK' if abs(wr-0.5)<0.05 else 'NG'}")
    ok &= abs(wr - 0.5) < 0.05

    sr = shrug_raw(lm, "l")
    print(f"shrug_raw_l (正値): {sr:.3f} ... {'OK' if sr and sr>0 else 'NG'}")
    ok &= sr is not None and sr > 0

    recs = build_metrics(lm)
    n_judged = sum(1 for r in recs if r.get("judgment"))
    print(f"build_metrics: {len(recs)} 指標, 判定付き {n_judged} 件 ... "
          f"{'OK' if len(recs) >= 12 else 'NG'}")
    ok &= len(recs) >= 12

    print("SELFTEST:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


# ---------------------------------------------------------------
# main
# ---------------------------------------------------------------

def main():
    if args.selftest:
        selftest()

    if not args.input or not args.performer or not args.pose \
            or not args.direction:
        sys.exit("必須: -i 画像 --performer ID --pose ポーズID "
                 "--direction front|side|back (または --selftest)")

    now = datetime.datetime.now()
    meta = {
        "schema_version": SCHEMA_VERSION,
        "timestamp": now.isoformat(timespec="seconds"),
        "session_id": args.session or now.strftime("%Y-%m-%d"),
        "performer_id": args.performer,
        "pose_id": args.pose,
        "direction": args.direction,
        "threshold_set_version": THRESHOLD_SET_VERSION,
        "extractor_version": EXTRACTOR_VERSION,
    }

    lm, size = detect_landmarks(args.input)
    image_ref = store_session_files(args.input, lm, size, meta)

    records = []
    for frag in build_metrics(lm):
        rec = dict(meta)
        rec.update(frag)
        rec["image_ref"] = image_ref
        rec.setdefault("judgment", None)
        records.append(rec)

    path = append_records(records)
    n_un = sum(1 for r in records if r.get("unmeasurable"))
    log(f"{len(records)} 指標を追記 ({n_un} 件は測定不能) → {path}")
    log(f"元写真と抽出結果 → {os.path.join(DATA_DIR, os.path.dirname(image_ref))}")
    # 確認用に主要値を標準出力(1行サマリ、awk向け)
    summary = {r["metric_id"]: r["value_raw"] for r in records
               if not r.get("unmeasurable")}
    print(json.dumps({"session": meta["session_id"],
                      "performer": meta["performer_id"],
                      "pose": meta["pose_id"],
                      "direction": meta["direction"],
                      **summary}, ensure_ascii=False))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="姿勢測定データの取得・記録")
    p.add_argument("-i", "--input", help="入力画像")
    p.add_argument("--performer", help="演者ID (例: p001)")
    p.add_argument("--pose", help="キーポーズID。基準写真は baseline / baseline_shrug")
    p.add_argument("--direction", choices=["front", "side", "back"],
                   help="撮影方向")
    p.add_argument("--session", help="セッションID (省略時は今日の日付)")
    p.add_argument("--selftest", action="store_true",
                   help="合成データで幾何計算を検証(MediaPipe不要)")
    args = p.parse_args()
    main()
