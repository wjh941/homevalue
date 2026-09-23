# HomeValue · 房价预测与估值平台

[![CI](https://github.com/wjh941/homevalue/actions/workflows/ci.yml/badge.svg)](https://github.com/wjh941/homevalue/actions/workflows/ci.yml)

**在线演示(免费实例,15 分钟无访问会休眠,首次打开约 50 秒冷启动):**
### -> https://homevalue-wv6h.onrender.com

从公开数据出发的端到端 ML 项目:数据采集 -> 清洗 -> SQLite 数仓 + SQL 分析 ->
LightGBM 建模(含预测区间) -> 误差分析 -> FastAPI 服务 -> 仪表盘 -> A/B 实验设计 -> CI。

> 叙事:先做了房源管理系统(soul-room),然后想知道"一套房的合理定价是多少",于是有了这个项目。

## 核心数字

| 维度 | 数字 |
|---|---|
| 真实数据 | 226,729 行原始挂牌 -> 156,004 套唯一房源(北京 148,369 套) |
| 特征 | 19 个:16 个基础特征 + 小区/商圈目标编码 |
| 主指标 | 留出集 MAE **5,641 元/平米**,MAPE **7.85%**,R² **0.926**(5 折 CV:5,820 ± 13) |
| baseline 提升 | 线性回归 MAE 14,909 -> LightGBM+TE 5,641(**-62.2%**) |
| 预测区间 | p10/p90 分位模型,实测 80% 区间覆盖率 **75.3%** |
| 服务 | FastAPI + 3 模型推理,单并发 P95 **264ms**,8 并发 P95 **710ms**(400 请求 0 错误) |
| SQL | 9 个含窗口函数/CTE 的分析查询(RANK/LAG/NTILE/ROW_NUMBER/透视/帕累托) |
| 工程 | 30 个 pytest 用例、ruff 通过、GitHub Actions(lint+test+冒烟训练)、Docker、Render 部署 |

## 架构

```text
data/raw/*.csv          链家公开快照(可复现下载 scripts/fetch_data.py)
      |  scripts/build_db.py(清洗/解析/区名修复)
      v
SQLite 数仓             listings_raw -> listings_all -> listings(窗口去重取最新)
      |                       |
      | sql/03_analysis.sql   v
      |  (9 个分析查询)   scripts/train.py(4 组实验 + 分位模型)
      |                       |
      v                       v  models/ + reports/
FastAPI(api/main.py)—— /api/predict、/api/analysis/*、静态仪表盘
```

## 快速开始

```bash
pip install -r requirements.txt

# 1) 数据:下载公开快照(约 67MB)并建库
python scripts/fetch_data.py
python scripts/build_db.py

# 2) 训练:线性 baseline -> LGBM -> 加商圈 -> 调参(全部实验追加到 reports/metrics_log.jsonl)
python scripts/train.py --model linear --exp-id exp001
python scripts/train.py --model lgbm   --exp-id exp002
python scripts/train.py --model lgbm   --exp-id exp003 --full-features
python scripts/train.py --model lgbm   --exp-id exp004 --full-features --tune
python scripts/train.py --model lgbm   --exp-id exp005 --full-features --community-te

# 3) 误差分析(输出 reports/error_analysis.json + PNG)
python scripts/error_analysis.py

# 4) 服务 + 仪表盘
python scripts/export_analysis_cache.py     # 分析结果缓存(部署模式用)
uvicorn api.main:app --port 8000            # 打开 http://127.0.0.1:8000
```

没有真实数据也能跑通全链路(CI 即如此):
```bash
python scripts/make_synth.py --n 4000 && python scripts/build_db.py
python scripts/train.py --model lgbm --exp-id smoke --full-features
```

## 数据

- 来源:[linpingta/lianjia-eroom-analysis](https://github.com/linpingta/lianjia-eroom-analysis)(公开的链家/贝壳挂牌页快照,2022-2024)
- 快照即"在售房源列表",同一房源跨快照保留历史,支持挂牌价调价分析
- 清洗:hhid 去重、价格/面积合理域过滤(脏数据率约 2%)、字段解析(户型/楼层/朝向/年份)

### 数据质量发现(面试点)

1. **约 37% 的记录 area 字段填的是商圈/小区名,不是行政区。**
   处理:行政区白名单 + 两轮多数票修复(商圈->区 36,410 行命中;小区->区 因跨期小区不重叠仅 +107 行),
   其余归入「其他」。修复过程说明:exp002 指标先变差后(去掉脏值红利)配齐特征再变优,
   详见 [EXPERIMENTS.md](EXPERIMENTS.md) 结论 2。
2. **2024-09 快照为部分抓取(1,646 行)**,该期环比仅作参考。
3. **95.2% 的调价房源在降价**(14,456 套跨期调价,平均 -5.64%)——2023-2024 北京挂牌市场以降价为主。

## SQL 分析(sql/03_analysis.sql,README 与 API 共用)

| 查询 | 窗口/CTE 技术 |
|---|---|
| districts_rank 各区均价排名 | RANK() OVER |
| city_price_trend 均价环比 | LAG() OVER |
| top_bizcircle_per_district 区内 TOP3 商圈 | ROW_NUMBER() + PARTITION BY |
| price_deciles 单价十分位画像 | NTILE(10) |
| layout_crosstab 区 x 户型透视 | 条件聚合 |
| price_change_summary / biggest_price_drops | 价格变动视图(相关子查询取相邻快照) |
| city_compare 多城市对比 | 分组聚合上的 RANK() |
| pareto_value 总价 TOP20% 金额占比 | ROW_NUMBER + COUNT(*) OVER |

示例(全市均价环比):

```sql
WITH t AS (
    SELECT snapshot_date, COUNT(*) AS n_listings,
           ROUND(AVG(unit_price), 0) AS avg_unit_price
    FROM listings_all WHERE city = 'bj' GROUP BY snapshot_date
)
SELECT snapshot_date, n_listings, avg_unit_price,
       ROUND((avg_unit_price - LAG(avg_unit_price) OVER (ORDER BY snapshot_date)) * 100.0
             / LAG(avg_unit_price) OVER (ORDER BY snapshot_date), 2) AS mom_pct
FROM t ORDER BY snapshot_date;
```

结果:75,551(2022-09)-> 76,143(+0.78%)-> 74,025(-2.78%)-> 69,300(-6.38%)。

## 建模

- 目标取 log(unit_price),指标换算回原尺度;随机 80/20 切分,训练集内 5 折 CV
- 特征 16 个:面积、室/厅、厅室比、总楼层、楼层位置序数、建成年份、房龄(+缺失标记)、
  朝向 4 哑元 + 朝向数、区/商圈/装修(低频类折叠为 __other__)
- 线性 baseline(ColumnTransformer + OneHot) -> LightGBM -> +商圈 -> 网格调参 -> **小区/商圈目标编码**
- 目标编码:**折内拟合防泄漏**,平滑系数 k=20(样本少的小区向全局均价收缩),线上未见类别回落先验,
  MAE 6,824 -> 5,641(**-17.3%**,见 EXPERIMENTS.md 结论 5)
- 预测区间:q10/q90 两个 quantile 目标的 LightGBM,实测覆盖率 75.3%

完整实验对比与结论见 [EXPERIMENTS.md](EXPERIMENTS.md)。

## 误差分析(reports/error_analysis.json)

- 整体:MAE 5,641,中位相对误差 6.0%,72.6% 的房源误差 ≤ 10%,**94.0% ≤ 20%**
- **低价段(<3 万/平米)MAPE 15.1% 且系统性高估(bias +3,312)** —— 典型的向均值回归
- 中间价格段(8-12 万)最准(MAPE 7.2%),是大多数用户所在区间
- 区域上高单价老城区误差率最高(MAPE ~9.1%)

## 服务与仪表盘

**线上环境**:https://homevalue-wv6h.onrender.com(Render Blueprint 部署,免费档)

```bash
uvicorn api.main:app --port 8000
```

| 端点 | 说明 |
|---|---|
| POST /api/predict | 输入房源参数,返回 p10/p50/p90 单价、总价、区间宽度、区/商圈可比均价 |
| GET /api/analysis/overview | 在售量、各区排名、帕累托份额 |
| GET /api/analysis/trend | 挂牌均价环比 |
| GET /api/analysis/deciles | 十分位画像 |
| GET /api/analysis/price-changes | 调价汇总 + 降价 TOP20 + 城市对比 |
| GET /api/analysis/errors | 误差分析报告 |
| GET /api/health | 版本/指标/数据后端(sqlite 或 cache) |

仪表盘(原生 JS + 手写 SVG,无前端依赖):估值表单 + 区间可视化 / 市场分析 /
模型洞察(特征重要性、分群误差)三个视图。

## A/B 实验设计

[experiments/ab_design.md](experiments/ab_design.md):「预测区间 vs 仅点估计」完整设计 ——
假设、OEC 与护栏指标、样本量(每臂 3,841,alpha=0.05,power=0.8)、确定性分流、SRM 检查、
peeking 约束与决策规则;统计实现(homevalue/ab.py)经蒙特卡洛验证(功效 81.1%、假阳性 4.0%)。

## 工程化

- 测试:30 个 pytest 用例(特征解析/清洗/ETL/SQL/API/A-B 统计),曾实际抓出 ETL 窗口误用与
  训练-服务特征不一致两个真 bug
- CI:.github/workflows/ci.yml —— ruff + pytest;手动冒烟任务用合成数据跑通全链路
- 部署:预训练产物与缓存随仓库走,克隆即可 Docker 部署,见 [DEPLOY.md](DEPLOY.md)

## 已知局限

- 挂牌价非成交价,存在挂牌偏倚;快照样本受爬虫分页策略影响(各区 3,000 行上限)
- 无经纬度/地铁距离等空间特征;小区粒度特征未做 target encoding
- 区间覆盖率 75.3% 略低于名义 80%,可通过 conformal prediction 校准(下一步)

## 目录结构

```text
homevalue/        核心包:features(解析/特征) data_clean db model ab
scripts/          fetch_data / build_db / train / error_analysis / export_analysis_cache / benchmark_api / make_synth
sql/              01_schema / 02_etl / 03_analysis
api/              FastAPI 服务 + static 仪表盘
tests/            pytest(30 用例)
experiments/      A/B 设计文档 + 蒙特卡洛仿真
models/ reports/  预训练产物 / 指标台账与误差报告
```

## 数据合规声明

数据来自公开抓取的第三方仓库,仅用于技术研究;模型输出为统计估值,不构成交易建议。
