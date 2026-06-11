# Phase 1.5 go/no-go 判定基準

日付: 2026-06-11  
関連: taichi_eval_spec_v1.2.md §12 Phase 1.5

---

## 背景

D系要訣（骨盤の立ち・含胸・抜背）はシルエット（セグメンテーションマスク）解析に
依存するため、「判別可能か」を事前に実験で確認する必要がある。

本書は、その go/no-go 判定に使う評価基準とその根拠を定める。

---

## 推奨評価基準

以下の2基準を**両方**満たす場合に「シルエット解析で実装可能」と判定する。
どちらか一方でも満たさない場合は「不可能または追加調査が必要」とし、
SMPL系メッシュ復元（4D-Humans 等）への移行を検討する。

---

## 基準 1: S/N 比 ≥ 3（最低ライン）、≥ 5（実用ライン）

### 測定方法

```
S/N = キャリブ2点の差 / 同条件繰り返し撮影の標準偏差（SD）

キャリブ2点:
  - 点A: 预备式（D系の基準・ゼロ点）
  - 点B: わざと崩した立位（例: 腰をそらした、含胸強調）

繰り返し撮影:
  - 同姿勢・同条件（服装・背景・カメラ位置）で連続 N 回撮影
  - 推奨 N ≥ 5（最低 N = 3）
  - SD を「ノイズ床」として記録する
```

### 判定閾値

| S/N | 判定 |
|-----|------|
| ≥ 5 | 実用可能（推奨ライン） |
| 3〜5 | 最低限の検出は可能。実稽古への適用は慎重に |
| < 3 | 測定不能（ノイズに埋もれている） |

### 根拠

**① 分析化学の検出限界（LOD: Limit of Detection）**

化学分析における「測定できる」の国際的定義：

```
LOD = ブランク平均 + 3 × σ_blank
  → 信号がノイズのSD の 3倍を超えれば「存在を検出できる」
```

> Long, G. L.; Winefordner, J. D. (1983).  
> "Limit of Detection: A Closer Look at the IUPAC Definition."  
> *Analytical Chemistry*, 55(7), 712A–724A.

ICH（医薬品規制調和国際会議）もバリデーション基準として同原則を採用：

> ICH Harmonised Guideline Q2(R2):  
> *Validation of Analytical Procedures* (2023).  
> https://www.ich.org/page/quality-guidelines

LOD（S/N = 3）は「あるかないかを見分けられる」水準であり、
定量的に使うには LOQ（S/N = 10）が目安となる。
本プロジェクトでは「変化の方向と大小を見る」用途なので S/N = 5 を実用ラインとした。

**② 製造業の計測システム評価（Gage R&R、MSA）**

計測システムが識別できるカテゴリ数（ndc: Number of Distinct Categories）：

```
ndc ≈ 1.41 × S/N
ndc ≥ 5 が「使える計測器」の合格基準
  → S/N ≥ 5 / 1.41 ≈ 3.5 に相当
```

> Automotive Industry Action Group (AIAG).  
> *Measurement Systems Analysis (MSA) Reference Manual*, 4th ed. (2010).  
> AIAG, Southfield, MI. （商業出版物）

NIST の統計ハンドブックにも同原則の解説がある：

> NIST/SEMATECH e-Handbook of Statistical Methods.  
> "Gage R&R."  
> https://www.itl.nist.gov/div898/handbook/

---

## 基準 2: Cohen's d ≥ 1.0（最低ライン）、≥ 1.5（実用ライン）

### 測定方法

```
Cohen's d = (点B の平均 − 点A の平均) / 合算 SD（pooled SD）

点A: 预备式を N 回撮影 → 指標の平均・SD を求める
点B: 崩した姿勢を N 回撮影 → 指標の平均・SD を求める
合算 SD = √[(SD_A² + SD_B²) / 2]
```

### 判定閾値

| d | Cohen の慣例的呼称 | 本プロジェクトでの判定 |
|---|-------------------|-----------------------|
| < 0.5 | small | 測定不能 |
| 0.5〜0.8 | medium | キャリブ2点さえ区別できない。実用不可 |
| 0.8〜1.0 | large | グループ比較なら有効。1枚判定には不十分 |
| ≥ 1.0 | very large | フィジビリティ最低ライン |
| ≥ 1.5 | — | 1枚判定の誤分類率 ≈ 7%。実用ライン |
| ≥ 2.0 | — | 誤分類率 ≈ 2%。十分 |

### 根拠

Cohen's d は平均差をSDで正規化した効果量の指標。
慣例的基準（small=0.2, medium=0.5, large=0.8）の出典：

> Cohen, J. (1988).  
> *Statistical Power Analysis for the Behavioral Sciences* (2nd ed.).  
> Lawrence Erlbaum Associates, Hillsdale, NJ.

短い解説論文：

> Cohen, J. (1992).  
> "A power primer."  
> *Psychological Bulletin*, 112(1), 155–159.

**Cohen の慣例はグループ比較向けであることの注意**

Cohen の基準はN人グループの平均を比べる文脈で設計されており、
グループサイズが増えると検出力が上がる（√N 効果）。

本プロジェクトは**1枚の写真から判定**するため、√N 効果が使えない。
分布の重なりを誤分類率に換算すると：

| d | 2分布の重なり率 | 1枚判定の誤分類率（目安） |
|---|---------------|--------------------------|
| 0.5 | 約80% | 約31% |
| 1.0 | 約62% | 約16% |
| 1.5 | 約43% | 約 7% |
| 2.0 | 約32% | 約 2% |

d = 1.0 は「6回に1回ハズれる」水準であるため、
フィジビリティの足切りとして使い、実用判断には d ≥ 1.5 を推奨する。

---

## 2基準の関係

S/N 比と Cohen's d は本質的に同じ量を異なる文脈で表現している：

```
S/N  = (2点の平均差) / ノイズSD（繰り返し撮影のSD）
d    = (2点の平均差) / 合算SD（両条件を合わせたSD）

どちらも「差 / ばらつき」の比。
繰り返し撮影のSD ≈ 合算SD であれば S/N ≈ d となる。
```

実際には姿勢の自然ゆらぎ（同姿勢でも毎回微妙に違う）が合算SDに上乗せされるため、
**S/N ≥ 5 かつ d ≥ 1.5 を両方確認する**ことが、相互検証として機能する。

---

## 実験手順（推奨）

1. 同条件でキャリブ2点（预备式・崩し姿勢）を各 N=5 回以上撮影
2. シルエット指標（腰くぼみ深さ等）を各写真から抽出
3. S/N と Cohen's d を算出（スクリプト化推奨）
4. 上記閾値で判定 → go/no-go を記録

測定ノイズ床の値は `measurements.jsonl` に `metric_id="silhouette_noise_xxx"` 等で記録し、
Phase 2 以降の経時評価にも使用する（仕様書 §5.3 参照）。

---

## 判定結果の記録フォーマット（例）

```json
{
  "experiment_date": "2026-XX-XX",
  "metric_id": "lumbar_concavity_depth",
  "direction": "side",
  "n_shots_per_condition": 5,
  "noise_sd": 3.2,
  "calib_delta": 18.5,
  "snr": 5.8,
  "cohens_d": 1.7,
  "judgment": "go",
  "notes": "Tシャツ着用、白壁背景"
}
```
