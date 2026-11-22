# 新手部署指南：从买服务器到公网访问（全流程）

> 目标读者：第一次部署 Web 项目的新手。
> 读完你会完成：买服务器 → 装环境 → 部署本系统 → 绑定域名开 HTTPS → 公网可访问。
> 进阶内容（迁移补丁、回滚细则、评测闸门）在 [DEPLOY.md](../DEPLOY.md) 和 [release-checklist.md](release-checklist.md)，本文只讲「怎么从零跑起来」。

---

## 0. 先回答你的三个问题

### 需要云服务器吗？——**需要**

本系统由「前端网页 + 后端接口 + 数据库」三部分组成，公网用户访问必须有一台 24 小时在线的机器来跑它们。家用电脑不适合（断电断网、IP 不固定），所以要买一台**云服务器（VPS / 轻量应用服务器）**。

### 需要域名吗？——**不是必须，但强烈建议**

- **不要域名也能用**：直接访问 `http://服务器IP:8080` 即可（适合内部测试）。
- **要域名的情况**：想让家长/老师通过 `https://xxx.com` 访问、需要 HTTPS 加密、需要微信/公众号生态对接。域名几十元/年。
- **重要区别**：
  - 服务器买在**中国大陆**（阿里云/腾讯云/蓝驰云等）→ 域名必须做 **ICP 备案**（免费，但审核约 7–20 天）；
  - 服务器买在**香港 / 海外** → 免备案，立刻可用，代价是国内访问延迟略高。

### 服务器要什么配置？——**最低 2核2G，推荐 2核4G**

| 档位 | CPU/内存 | 磁盘 | 带宽 | 适用场景 |
| --- | --- | --- | --- | --- |
| 最低能跑 | 2核 2G | 40G SSD | 3M | 个人试用，构建时可能吃紧 |
| **推荐** | 2核 4G | 60G SSD | 5M | 小机构正式使用（本系统默认目标） |
| 更宽裕 | 4核 8G | 80G SSD | 5–10M | 用户量大 / 想开全部 AI 增强 |

> 为什么内存是重点：数据库 + 后端常驻约占 1G；`npm run build` 构建前端时瞬时吃 1.5–2G。2G 内存的机器建议加 2G swap（见 FAQ Q2），4G 则从容。

**在蓝驰云（lcayun）购买时对照着选**：

- 产品类型选「云服务器 / 轻量应用服务器」——**不要选虚拟主机**（虚拟主机装不了 Docker，本系统必须用 Docker 部署）；
- 系统镜像选 **Ubuntu Server 22.04 或 24.04 LTS（64 位）**——不要选 Windows Server（白花钱、用不上图形界面）；
- 新人活动机常见 2核2G/2核4G，够用；超过 8G 内存对本系统是浪费；
- 带宽按「按固定带宽」买 3–5M 即可（本系统页面很轻，主要传几张截图）；
- 有「快照/备份」附加项建议勾上（出事能回滚整机）。

**价格量级**（2026 年市场，仅供参考）：2核2G 约 50–80 元/月，2核4G 约 80–150 元/月；新用户首年常有 3–5 折。蓝驰云属于国内中小云厂商，价格通常低于大厂，购买前确认：是否送快照、是否限制流量、续费价格（新购便宜的机器续费常翻倍）。

---

## 1. 术语小词典（看不懂部署命令时回来查）

| 术语 | 一句话解释 |
| --- | --- |
| SSH | 远程登录服务器的协议。你从自己电脑「命令行进到服务器里」敲命令 |
| 安全组 / 防火墙 | 云厂商在机器外面又加的一道门，**端口不开，外面永远连不进来**（最常踩的坑） |
| 端口 | 一台机器上用数字区分不同服务。网页走 80（HTTP）/443（HTTPS），本系统应用层默认 8080 |
| Docker | 「软件集装箱」。本系统的数据库/后端/前端被打包成 3 个容器，一条命令启动 |
| Docker Compose | 管多个容器的小管家（本项目的 `docker-compose.yml` 就是它的配置） |
| 反向代理 | 外面访问 80/443 端口的流量，转交给内部 8080 的服务处理 |
| DNS 解析 | 把域名（xxx.com）指向服务器 IP 的记录，在域名控制台配置 |
| ICP 备案 | 大陆服务器的域名实名登记，免费但要等审核 |
| SSL 证书 / HTTPS | 让浏览器地址栏出现小锁的证书，宝塔/Let's Encrypt 可免费申请 |
| 宝塔 / 堡塔多机管理 | 国产服务器管理面板，图形化装软件、管文件、配网站、申请证书。你已安装的「堡塔多机管理」可以在一个界面里管理多台服务器 |

---

## 2. 第一步：购买并初始化服务器

1. 在蓝驰云下单（配置见第 0 节），系统选 **Ubuntu 22.04/24.04**；
2. 记下三样东西：**公网 IP、root 密码（或密钥）、SSH 端口（一般 22）**；
3. **开安全组端口**（控制台 → 防火墙/安全组）——至少放行：

> ⚠️ 这一步没做，后面所有访问都会超时。

| 端口 | 用途 |
| --- | --- |
| 22 | SSH 登录（建议只放行你自己的 IP） |
| 80 | HTTP（网站） |
| 443 | HTTPS（网站加密） |
| 8080 | 本系统默认端口（配好域名后可不对外开） |

4. 用**堡塔多机管理**添加这台机器：面板里「添加服务器」→ 填 IP / root 密码 → 连接成功后可打开网页终端（不用装 Xshell 等工具）。

---

## 3. 第二步（可选）：域名与备案

1. 哪里买域名：阿里云 / 腾讯云 / 蓝驰云（同一家买迁移方便），`.com`/`.cn` 约 30–80 元/年；
2. 域名要**实名认证**（多数平台下单时强制）；
3. 服务器在大陆 → 找服务器厂商做 **ICP 备案**（在云厂商控制台里发起，需身份证/营业执照 + 域名证书，审核 7–20 天）；
4. 备案期间可以用 `http://IP:8080` 先把系统跑起来测试，不影响后续；
5. 备案通过后做 **DNS 解析**：
   - 类型 `A`，主机记录 `@`（就是 xxx.com）指向服务器 IP；
   - 再来一条 `A`，主机记录 `www`，同样指向 IP；
   - 用 `ping xxx.com` 能返回你的 IP 即生效（一般 10 分钟内）。

> 不想等备案：把服务器买在香港节点即可免备案，其他步骤完全一样。

---

## 4. 第三步：在服务器上装 Docker

在堡塔多机管理的「网页终端」里执行（全程复制粘贴）：

```bash
# 1) 系统更新（可选但推荐）
sudo apt update && sudo apt upgrade -y

# 2) 一键安装 Docker（官方脚本，国内服务器若卡住用第 3 步的镜像脚本）
curl -fsSL https://get.docker.com | sudo sh

# 3) 国内镜像加速（可选）：写入 /etc/docker/daemon.json 后重启
sudo mkdir -p /etc/docker
sudo tee /etc/docker/daemon.json >/dev/null <<'EOF'
{ "registry-mirrors": ["https://docker.1ms.run", "https://docker.m.daocloud.io"] }
EOF
sudo systemctl restart docker

# 4) 验证（出现版本号就成功）
docker --version && docker compose version
```

> 如果面板自带「Docker 管理」功能（宝塔应用商店里有 Docker 插件），也可以点按钮装，等效。

---

## 5. 第四步：部署本系统

### 5.1 把代码放到服务器

```bash
cd /opt
git clone <你的仓库地址> Child_Code   # 或从本地上传压缩包解压
cd Child_Code
```

### 5.2 填写生产配置

```bash
cp .env.prod.example .env.prod
nano .env.prod        # 或面板的文件管理器里编辑
```

**必须改的 3 项**（新手最容易漏）：

| 变量 | 怎么填 |
| --- | --- |
| `SECRET_KEY` | 随机长串。生成方法：`python3 -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `POSTGRES_PASSWORD` | 数据库密码，自己编一个强的（字母+数字 16 位以上） |
| `SEED_ADMIN_PASSWORD` | 首个管理员 admin 的登录密码 |

**建议按需改的**：

| 变量 | 说明 |
| --- | --- |
| `WEB_PORT` | 对外端口。先保持 `8080` 测试；如果打算用 80 直出，改 `80`（需确认 80 没被面板占用） |
| `APP_ENV` | 保持 `prod`（启动时会强校验上面的密钥配置） |
| `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` | AI 功能（出题/评语/RAG）用。不填也能启动，AI 相关功能自动走兜底 |
| `CORS_ORIGINS` | 同域访问可留空；前后端分域名时填前端地址 |

### 5.3 启动

```bash
docker compose up -d --build     # 首次约 5–10 分钟（要装依赖 + 编译前端）
docker compose ps                # 三个容器都是 running/healthy 即成功
```

> 首次启动会自动建表（`alembic upgrade head`），**全新建的服务器无需任何迁移操作**。

### 5.4 创建首个管理员

```bash
docker compose exec backend .venv/bin/python scripts/seed_admin.py
```

### 5.5 立刻验证

浏览器打开 `http://服务器IP:8080`，用 `SEED_ADMIN_USERNAME`（默认 admin）+ 刚才设的密码登录。

---

## 6. 第五步：域名 + HTTPS（正式上线）

两种做法选一种，**推荐 A（宝塔反代）**，因为你有堡塔多机管理在手。

### 方案 A：宝塔面板建站反代（推荐）

1. 在服务器上或通过面板应用商店安装宝塔面板（单机版即可，多机管理用来连它）；
2. 面板 → 网站 → 添加站点，域名填 `xxx.com`；
3. 站点设置 → **反向代理** → 目标 `http://127.0.0.1:8080`（即本系统），保存；
4. 站点设置 → **SSL** → Let's Encrypt → 一键申请并强制 HTTPS；
5. 回到 `.env.prod` 把 `WEB_PORT` 改成 `8090`（或任意本机端口），`docker compose up -d` 重启——避免和宝塔的 80 端口冲突；同时把安全组里对外暴露的 8080 关掉。

### 方案 B：不改任何配置，compose 直接占 80

1. `WEB_PORT=80` 后 `docker compose up -d`；
2. HTTPS 用 1Panel/Caddy 或在云厂商申请免费证书后挂到外层 Nginx。

> 验收标准：浏览器访问 `https://xxx.com`，地址栏有锁、能登录，即完成。

---

## 7. 第六步：上线检查（15 分钟）

- [ ] 打开 [冒烟清单 smoke-checklist.md](smoke-checklist.md)，按 A–F 走一遍；
- [ ] 后台「系统设置」确认环境正常；「审计日志」能看到你的操作记录；
- [ ] 把 `.env.prod` 里 `SEED_ADMIN_*` 三行删掉（密码已生效，避免泄露）；
- [ ] 配每日备份 cron：

```bash
# 编辑 crontab：crontab -e，加一行（每天 02:30 备份，保留 30 天）
30 2 * * * /opt/Child_Code/backend/scripts/backup.sh >> /var/log/child_code_backup.log 2>&1
```

- [ ] 全量细节核对 [release-checklist.md](release-checklist.md)。

---

## 8. 日常运维速查

```bash
docker compose ps                          # 看状态
docker compose logs -f backend             # 看后端日志（Ctrl+C 退出）
docker compose up -d --build               # 发版：git pull 后重建
git checkout <上一个tag> && docker compose up -d --build   # 回滚代码
```

- 备份/恢复：见 [DEPLOY.md](../DEPLOY.md) §5 与 `backend/scripts/restore_drill.md`；
- 升级出问题：优先回滚代码，**不要**对生产库执行 `alembic downgrade`（会清空数据）；
- 数据回滚只能走备份恢复（先恢复到临时库验证，再切换）。

---

## 9. FAQ（新手最常问）

**Q1：浏览器打不开 / 一直转圈？**
按顺序查：① 容器起来了没（`docker compose ps`）→ ② 安全组端口开了没（80/443/8080）→ ③ 服务在监听没（`curl -I http://127.0.0.1:8080` 在服务器上执行）→ ④ 宝塔反代目标对不对。

**Q2：2G 内存构建前端时卡死 / 容器自动退出？**
加 swap：

```bash
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

**Q3：备案还没下来，网站能先上线吗？**
能。用 `http://IP:8080` 先内测；对外正式用需要备案完成（大陆机器）或换香港机器。

**Q4：AI 功能报「没有可用的 AI 模型」？**
登录后台 → 设置 → 模型配置，添加接口地址/API Key/模型名（如 DeepSeek/通义），或在 `.env.prod` 填 `LLM_*` 后重启。不配也不影响教务/财务等主流程。

**Q5：数据库密码 / SECRET_KEY 能事后改吗？**
`POSTGRES_PASSWORD` 改后需同步重置数据库容器内密码（麻烦，初始就设对）；`SECRET_KEY` 轮换有专门支持（见 `.env.prod.example` 的 `SECRET_KEY_PREVIOUS` 注释）。

**Q6：怎么升级到新版本？**
服务器上 `git pull` → `docker compose up -d --build` → 看启动日志 → 跑一遍冒烟清单。涉及表结构变化的版本按 [release-checklist.md](release-checklist.md) 的窗口流程走。
