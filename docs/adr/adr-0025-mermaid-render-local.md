# ADR-0025：Mermaid 图表渲染本地化（npm 打包 + 懒加载）

- 状态：已采纳
- 日期：2026-11-12
- 关联：ADR-0024、CONTEXT.md、frontend/src/utils/mermaid.ts、frontend/src/utils/markdown.ts

## 背景（Context）

Agent 工作台对话中的 mermaid 围栏原通过运行时从 `cdn.jsdelivr.net` 加载 mermaid@10 渲染，且失败时静默保留源码。国内网络/内网环境加载 CDN 经常失败，用户只能看到代码；`catch {}` 吞掉错误导致无法定位。分享会话页与开发文档页则完全没有渲染钩子，文档里的流程图永远显示为源码。开发文档中部分模块（架构、RAG 链路、对话时序、发版闸门）用流程图表达显著优于纯文字。

## 决策（Decision）

1. **依赖本地化**：mermaid 改为 npm 依赖（`^12`），通过动态 `import('mermaid')` 懒加载（独立 chunk，首屏不加载）。
2. **统一渲染工具**（`utils/markdown.ts` + `utils/mermaid.ts`）：mermaid 围栏输出「源码 `<pre>` + 空 `.mermaid-render` 容器」；渲染工具以源码文本调用 `mermaid.render(id, src)` 写入 SVG（避免 innerHTML 实体转义问题），初始化 `securityLevel: 'strict'`。
3. **失败可见**：渲染失败在容器内显示错误原因 + 「重试」按钮，源码保持可见、复制按钮可用；重试通过容器事件代理（`bindMermaidRetry`）。
4. **接入三处**：Agent 工作台（`AgentsView`）、分享会话页（`SharedConversationView`）、开发文档页（`DocsView`）；并给 architecture / rag-admin / ai-agent / ops 四篇文档补充流程图（分层请求链路、检索管线、对话时序、发布闸门）。

## 后果（Consequences）

- 不再依赖外网 CDN，离线/内网可用；mermaid 加入构建产物（懒加载 chunk，约数百 KB gzip 前）。
- 错误不再静默，用户与开发者都能看到具体解析错误并可重试。
- 家长客服对话（`Parent…` 未接入）不做渲染，避免向家长暴露内部流程图；如需接入复用同一工具即可。
