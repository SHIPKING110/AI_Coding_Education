# ppt-master 兼容适配版（工作台）

把官方 [ppt-master](https://github.com/hugohe3/ppt-master) 打包为**一条命令出片**的版本，
解决在工作台里"生成不稳、二次编辑乱"的问题。生成质量与官方一致（只是把多步流程收成单入口）。

## 为什么需要它

官方流程是多阶段**交互式**的（project_manager → 质量门禁 → 导出，外加确认 UI、模板候选、图片获取）。
工作台模型的工具调用预算有限，自己摸这套多步路由极易漏步走偏。适配版用 `scripts/ppt_oneshot.py`
把最稳的链路封成单入口，模型只需"写 SVG → 跑一条命令"。

## 工作台快速通道（SKILL.md 顶部已写入）

生成：
1. 每页写成 SVG 放进 `<项目>/svg_output/`（01_cover.svg、02_... 顺序即页序，用 write_skill_file 写入）
2. `python3 ".../scripts/ppt_oneshot.py" build <项目>` → 质量门禁 + 导出 pptx（产物自动回链）

二次编辑（保留原设计、只重建改动页）：
1. `ppt_oneshot.py edit <源.pptx> <工作区>` 导入为可编辑工作区
2. 改工作区里的 `svg_output/*.svg`
3. `ppt_oneshot.py export <工作区>` 导出

## 安装

在容器内执行（幂等）：

```bash
docker compose exec backend python scripts/seed_ppt_master_adapter.py --owner admin --publish
```

或手动：工作台「我的 Skill → 导入 ZIP」上传 `seed_skills/ppt-master-adapter.zip`，再发布到广场。

## 已验证

容器内实测：`ppt_oneshot.py build` 通过工作台 `run_skill_script` 工具跑通，成功导出 `.pptx`（含质量门禁）。
