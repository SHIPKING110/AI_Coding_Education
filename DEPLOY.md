# 生产部署手册（DEPLOY）

目标：单机 Docker Compose 一键起生产环境（Postgres + 后端 + 前端同域反代）。

## 1. 前置要求

- 服务器安装 Docker Engine 24+（含 compose v2 插件），开放 80/443（或自定义 `WEB_PORT`）。
- 如需 HTTPS，自行在 `web` 前加反代（如 Nginx/Caddy）做证书，本 compose 默认 HTTP。

## 2. 首次部署（约 5 分钟）

```bash
# 1) 取代码
git clone <repo> && cd Child_Code

# 2) 填写生产配置（逐项改，尤其是三个“请替换”）
cp .env.prod.example .env.prod
# SECRET_KEY 换随机值：python -c "import secrets; print(secrets.token_urlsafe(48))"

# 3) 构建并启动（首次含 npm build + pip install，约 3-8 分钟）
docker compose --env-file .env.prod up -d --build

# 4) 创建首个管理员（幂等，可重复执行）
docker compose exec backend python scripts/seed_admin.py

# 5) 打开 http://服务器IP:8080（或 WEB_PORT）登录
```

## 3. 表结构同步

- 后端启动时自动执行 `create_all` + 幂等 `addcol`，**无需手动迁移**；发版后 `docker compose up -d --build backend` 重启即同步。
- 旧 alembic 链仅保留历史参考，不再参与部署流程。

## 4. 已知生产约束（重要）

- **单 worker**：AI 出题/评估任务状态在进程内存，多 worker 会导致建任务与轮询落到不同进程。需要扩容时，先把任务状态外置（DB/Redis）再加 worker。
- **AI 重型依赖不在镜像内**：langchain/chromadb/sentence-transformers（torch，体积大）未进生产镜像，相关 AI 增强走兜底；PPT/PDF/DOCX 导出依赖已包含，正常可用。如需完整 AI 能力，服务器可科学上网后在镜像构建时加 --extra ai。
- **微信推送**：未接入（需商户资质），通知走应用内站内信。

## 5. 日常运维

```bash
docker compose ps                    # 看状态
docker compose logs -f backend       # 看后端日志
docker compose up -d --build         # 发版更新

# 数据库备份（每日建议 cron）
docker compose exec db pg_dump -U app child_code > backup-$(date +%F).sql
# 恢复
cat backup.sql | docker compose exec -T db psql -U app child_code

# 上传文件备份（聊天截图等在命名卷 uploads 中）
docker run --rm -v child_code_uploads:/data -v $(pwd):/bak alpine tar czf /bak/uploads-$(date +%F).tgz /data
```

## 6. 生产 checklist（上线前逐项打勾）

- [ ] `SECRET_KEY` / `POSTGRES_PASSWORD` / `SEED_ADMIN_PASSWORD` 均为随机强密码
- [ ] `DEBUG=false`；`.env.prod` 未提交版本库
- [ ] 如前后端分域名：`CORS_ORIGINS` 填前端域名；同域反代可留空
- [ ] LLM key 按需配置（不配则 AI 出题/评估走兜底，不影响主流程）
- [ ] 备份 cron 已配（数据库 + uploads 卷）
- [ ] 首个 admin 已创建；`SEED_ADMIN_*` 可从 `.env.prod` 删除
- [ ] 全量回归通过：`pytest` / `ruff` / `npm run build`

## 7. 回滚

```bash
git checkout <上一个tag/commit> && docker compose up -d --build
# 数据回滚用第 4 节的备份恢复（注意：新代码产生的数据可能与旧代码不兼容，先在测试环境验证）
```
