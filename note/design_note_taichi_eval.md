# 設計メモ: 解析エンジン taichi_eval.py（未実装・実装時に読むこと）

日付: 2026-06-10
関連: taichi_eval_spec_v1.2.md / taichi_record.py

## 基本アーキテクチャ: 評価 = 対象セレクタ × 基準セレクタ

解析プログラムは機能別（スナップショット用・推移用…）に分けず、
**「何を取り出すか(--target)」×「何と比べるか(--vs)」の2セレクタを受ける
1つの照合エンジン**として作る。

```sh
# 今日のスナップショット(閾値・規定と照合)
taichi_eval.py --target p001:today --vs thresholds

# 過去3ヶ月の推移(ノイズ床と照合)
taichi_eval.py --target p001:2026-03-01..today --vs trend

# 過去の任意の一点との比較
taichi_eval.py --target p001:today --vs p001:2026-03-01

# 先生(お手本統計)との比較
taichi_eval.py --target p001:today --vs ref:loushi_aobu

# 拡張例: 自己ベスト比較もコンパレータ追加だけで足せる
taichi_eval.py --target p001:today --vs p001:best
```

- target セレクタ: performer_id / session・期間 / pose_id / metric_id で
  measurements.jsonl を絞り込む
- vs コンパレータ: thresholds(A) / ref統計(B) / baseline(C・D) /
  任意セッション / trend(ノイズ床) … 差し替え可能なプラグイン構造
- 新しい比べ方 = コンパレータを1個追加するだけ

## 守るべき規律

1. **解析側は measurements.jsonl に書き込まない**（読み取り専用。
   出力は reports/ へ）。書く者(taichi_record.py)と読む者の分離が
   独立性の生命線。
2. **記録済みの judgment は信用せず、生値(value_raw)から再計算する**。
   レコード内の判定(墜肘など)は記録時の便宜的キャッシュにすぎない。
   正本は常に生値＋閾値セットバージョン。
3. C・D の評価は target セッションの baseline / baseline_shrug
   レコードを引いて比率・変化量に換算する（記録側はやらない）。

## 実装順の候補

1. 最小実装: thresholds と trend の2コンパレータ
2. ref(お手本統計) … お手本登録機能(F4)とセット
3. baseline 換算(すくみ率・D変化量)
4. 任意セッション比較・best

## それまでのつなぎ

照合エンジンができるまでは jq/awk で直接読める:

```sh
jq -c 'select(.performer_id=="p001" and .metric_id=="elbow_flare_deg_r")' \
  data/measurements.jsonl
```
