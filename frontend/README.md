# Child Code 前端

基于 Vue 3 + Vite + TypeScript + Pinia + Vue Router 的智能少儿编程教育管理系统前端（管理端与客户端 H5 同源工程，按路由/视图分层）。

## 环境要求

- Node.js ≥ 18
- npm 或 pnpm

## 安装与运行（在 frontend/ 目录下执行）

```bash
cd frontend
npm install
npm run dev
```

开发服务器默认 http://127.0.0.1:5173，已将 `/api` 代理至后端 http://127.0.0.1:8000（见 vite.config.ts）。

## 构建

```bash
npm run build    # 类型检查 + 产物构建
npm run preview  # 预览构建产物
```

## 目录说明

- `src/api/` - axios 客户端（含 JWT 注入与自动刷新）与接口封装
- `src/stores/` - Pinia 状态（auth 认证 store）
- `src/router/` - 路由与登录守卫
- `src/views/` - 页面（auth/登录，Home 骨架）

## 说明

- M0 提供认证闭环骨架；业务页面（学员/排课/反馈/习题/客户端）随对应里程碑在本工程内扩展。