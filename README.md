# 太極拳姿勢評価プログラム - 成果物一式

作成日: 2026-06-10

## ディレクトリ構成

```
spec/               仕様書(Markdown)
  posture_compare_spec.md       初期プロトタイプ仕様書
  taichi_eval_spec.md           指導向け仕様書 v1.0
  taichi_eval_spec_v1.1.md      v1.1 (計測モデル4分類・キャリブレーション)
  taichi_eval_spec_v1.2.md      v1.2 (経時評価を主目的に昇格) ← 現行版

flow/               処理フロー図(draw.io XML, VSCodeで開く)
  posture_compare_flow.drawio   初期プロトタイプのフロー
  taichi_eval_flow.drawio       指導向けフロー v1.0
  taichi_eval_flow_v1.1.drawio  v1.1 (セッションキャリブレーション追加)

code_prototype/     初期プロトタイプ (pose.py が原点)
  pose.py           骨格+軸の可視化 (単体フィルタ)
  pose_angles.py    画像→関節角度JSON
  pose_compare.py   お手本と演者の差分比較

code_phase1/        Phase 1 実装
  taichi_record.py  データ取得プログラム(写真→measurements.jsonl追記)

note/               設計メモ
  design_note_taichi_eval.md    解析エンジン taichi_eval.py の設計方針
                                (セレクタ×コンパレータ方式、実装時に読むこと)
```

## 現状と次のステップ

- Phase 1 のデータ取得 (`taichi_record.py`) は実装済み・セルフテスト済み
- 解析エンジン (`taichi_eval.py`) は設計済み・未実装
  → note/design_note_taichi_eval.md を参照
- Phase 1.5: D系(骨盤・含胸・抜背)のシルエット解析予備実験が最大の不確定要素

## 依存パッケージ (Python 3.12, Mac Apple Silicon)

    pip install mediapipe opencv-python numpy matplotlib
