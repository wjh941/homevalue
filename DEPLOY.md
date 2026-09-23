# 部署指南

仓库里已提交预训练产物(models/)与预计算分析缓存(reports/analysis_cache.json),
因此**克隆即可部署**,不需要在服务器上下载数据集或重新训练。

## 方案 A:Railway / Render(推荐,支持 Docker)

1. 把仓库推到 GitHub
2. Railway: New Project -> Deploy from GitHub repo(自动识别 Dockerfile)
3. Render: New -> Web Service -> Environment 选 Docker
4. 启动命令(Dockerfile 已内置): uvicorn api.main:app --host 0.0.0.0 --port 8000
5. 健康检查路径: /api/health

## 方案 B:Docker 本地/任意 VPS

```bash
docker build -t homevalue .
docker run -p 8000:8000 homevalue
```

## 方案 C:Vercel / 无 Docker 平台

Vercel 只适合前端;FastAPI 建议放 Railway/Render/Fly.io。
若坚持前后端分离部署,可把 api/static 单独发 Vercel,
再把 API 地址写入前端 fetch 基址。

## 升级为「全量数据」部署(可选)

默认部署使用缓存分析;如果要带完整 SQLite 数仓(约 60MB):

```bash
python scripts/fetch_data.py        # 下载公开快照(约 67MB)
python scripts/build_db.py          # 建库
python scripts/export_analysis_cache.py
python scripts/train.py --model lgbm --exp-id exp003 --full-features
```

然后把 data/processed/listings.db 一并挂载/上传,
API 会自动从「缓存模式」切换为「SQLite 实时查询」(见 /api/health 的 data_backend)。

## CI/CD

- .github/workflows/ci.yml:push/PR 自动跑 ruff + pytest
- 手动触发 smoke-pipeline:合成小数据 -> 建库 -> 训练,验证全链路
