#!/usr/bin/env python3
"""
pose_compare.py - お手本(先生)と各演者の関節角度を比較する

依存:
    pip install numpy matplotlib

前提:
    pose_angles.py で各画像を JSON 化しておく。
        ./pose_angles.py -i teacher.jpg     > teacher.json
        ./pose_angles.py -i performer1.jpg  > p1.json
        ./pose_angles.py -i performer2.jpg  > p2.json

使い方:
    # お手本を --ref で、比較したい演者を並べる
    ./pose_compare.py --ref teacher.json p1.json p2.json

    # 重ね描き図(お手本=グレー, 演者=色)も PNG 出力
    ./pose_compare.py --ref teacher.json p1.json p2.json --figdir ./compare_out

出力:
    各演者について、関節ごとの「演者角度 - お手本角度」を表示。
    符号付きなので、+ は曲げすぎ/開きすぎ、- はその逆の傾向。
    visibility が低い関節は (!) を付けて警告(角度が当てにならない)。
    総合のズレ量(信頼できる関節のRMS)も出す。
"""

import sys
import os
import json
import argparse
import numpy as np

VIS_MIN = 0.5   # この値未満の関節は信頼できないとみなす

L_SH, R_SH, L_HP, R_HP = 11, 12, 23, 24
EDGES = [(11, 12), (11, 23), (12, 24), (23, 24),
         (11, 13), (13, 15), (12, 14), (14, 16),
         (23, 25), (25, 27), (24, 26), (26, 28)]


def load(path):
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    if not d.get("detected"):
        sys.exit(f"検出できていないJSONです: {path}")
    return d


def compare(ref, perf):
    """関節ごとの差分(perf - ref)と信頼性を返す"""
    rows = []
    for joint in ref["angles"]:
        ra = ref["angles"].get(joint)
        pa = perf["angles"].get(joint)
        rv = ref["visibility"].get(joint, 0)
        pv = perf["visibility"].get(joint, 0)
        if ra is None or pa is None:
            continue
        reliable = (rv >= VIS_MIN and pv >= VIS_MIN)
        rows.append({
            "joint": joint,
            "ref": ra,
            "perf": pa,
            "diff": round(pa - ra, 2),
            "reliable": reliable,
            "vis": round(min(rv, pv), 2),
        })
    return rows


def rms(rows):
    vals = [r["diff"] for r in rows if r["reliable"]]
    return float(np.sqrt(np.mean(np.square(vals)))) if vals else None


def print_report(name, rows):
    print(f"\n=== {name} ===")
    print(f"{'joint':<16}{'ref':>8}{'perf':>8}{'diff':>9}   note")
    for r in sorted(rows, key=lambda x: -abs(x["diff"])):
        note = "" if r["reliable"] else f"(! vis={r['vis']})"
        print(f"{r['joint']:<16}{r['ref']:>8.1f}{r['perf']:>8.1f}"
              f"{r['diff']:>+9.1f}   {note}")
    overall = rms(rows)
    if overall is not None:
        print(f"-- 総合ズレ(信頼関節のRMS): {overall:.1f} 度")


# ---- 重ね描き(matplotlib) ----
def norm_coords(d):
    """ヒップ中点を原点、肩中点-尻中点距離=1 に正規化したピクセル座標を返す"""
    w, h = d["image_size"]
    lm = {int(k): np.array([v[0] * w, v[1] * h]) for k, v in d["landmarks"].items()}
    sh = (lm[L_SH] + lm[R_SH]) / 2
    hp = (lm[L_HP] + lm[R_HP]) / 2
    scale = np.linalg.norm(sh - hp)
    if scale == 0:
        scale = 1.0
    return {i: (p - hp) / scale for i, p in lm.items()}


def draw_overlay(ref, perf, name, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    cr = norm_coords(ref)
    cp = norm_coords(perf)
    rows = compare(ref, perf)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 5))

    # 左: 骨格重ね描き。画像yは下向きなので y を反転して表示
    for a, b in EDGES:
        ax1.plot([cr[a][0], cr[b][0]], [-cr[a][1], -cr[b][1]],
                 color="0.6", lw=3, solid_capstyle="round")
    for a, b in EDGES:
        ax1.plot([cp[a][0], cp[b][0]], [-cp[a][1], -cp[b][1]],
                 color="crimson", lw=2, solid_capstyle="round")
    ax1.set_aspect("equal")
    ax1.axis("off")
    ax1.set_title(f"skeleton  gray=teacher  red={name}")

    # 右: 関節角度の差分(符号付き)
    rel = [r for r in rows]
    names = [r["joint"] for r in rel]
    diffs = [r["diff"] for r in rel]
    colors = ["crimson" if r["reliable"] else "0.7" for r in rel]
    y = np.arange(len(names))
    ax2.barh(y, diffs, color=colors)
    ax2.set_yticks(y)
    ax2.set_yticklabels(names)
    ax2.axvline(0, color="k", lw=0.8)
    ax2.set_xlabel("performer - teacher (deg)   gray bar = low visibility")
    ax2.set_title("joint angle difference")
    ax2.invert_yaxis()

    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    print(f"  図を保存: {path}", file=sys.stderr)


def main():
    ref = load(args.ref)
    if args.figdir:
        os.makedirs(args.figdir, exist_ok=True)

    summary = []
    for path in args.performers:
        perf = load(path)
        name = os.path.splitext(os.path.basename(path))[0]
        rows = compare(ref, perf)
        print_report(name, rows)
        summary.append((name, rms(rows)))
        if args.figdir:
            draw_overlay(ref, perf, name,
                         os.path.join(args.figdir, f"compare_{name}.png"))

    # お手本から遠い順のランキング
    ranked = sorted([s for s in summary if s[1] is not None], key=lambda x: -x[1])
    if ranked:
        print("\n=== お手本との総合ズレ(大きい順) ===")
        for name, v in ranked:
            print(f"  {name:<16}{v:>6.1f} 度")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="お手本と各演者の関節角度を比較")
    p.add_argument("--ref", required=True, help="お手本(先生)のJSON")
    p.add_argument("performers", nargs="+", help="比較する演者のJSON(複数可)")
    p.add_argument("--figdir", help="重ね描き図PNGの出力先ディレクトリ")
    args = p.parse_args()
    main()
