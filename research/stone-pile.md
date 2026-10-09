# 翻石头候选石头堆(2026-06-05)

> 来源:6 角度并行联网 sweep(MCP 注册表 / 论坛差评 / Product Hunt-Toolify 翻差评 / GitHub awesome+issue 空白 / skill 生态 / 通用能力短板)。
> 原始 44 块,去重后 44 块(名字不同但有语义重叠,下方已按主题聚类)。
> **铁律**:这是石头堆,值不值得做、做哪 10 个由 Tony 自己翻/填。

## 聚类(整理,不替选)

### A. Context/Token 瘦身(agent 最普遍的钱坑)
- **MCP瘦身代理**(mcp/strong):server↔agent 中间层做字段投影/分页/截断。Jira 单 ticket 67000→3900 token(降94%);Playwright 5万-20万 token;官方 25000 token 上限报错。证据:MCP issue #1576、HN 45954572、serena #516
- **按需工具加载层**(mcp/strong):5-10 个 MCP 装上去打字前先烧 50000-67000 token;40 工具占 200K context 的 72%。Perplexity CTO 2026-03 公开弃用 MCP。证据:thenewstack、jethroseghers
- **胖MCP收纳技能**(skill/strong):CMS 50 tool→8 tool,成功率 31%→89%;Copilot MCP 43 tool 全量加载比 CLI 多 32 倍 token。社区共识"many Skills, few MCP servers"
- **语义代码索引/代码库智能定位**(mcp/strong+medium):大仓 grep 答不出"怎么工作",73% 本地编过却违反别处 pattern,50 处改动烧 $80。openai/codex issue #5181 官方承认缺 semantic search

### B. 记忆与续命(Tony 自己 ledger/memory 正在补的洞)
- **跨会话记忆脑**(mcp/strong):新会话清零、重复解释架构;现有 memory MCP 只存取不抽事实/不链实体/不追时序。官方 memory server #692 #1018 高 reaction
- **断点续跑检查点**(skill/strong):200 文档跑到第 201 个崩→从头来;>80% model/domain 出现 catastrophic corruption(Microsoft 研究,The Register 2026-05-11)
- **压缩续命器**(skill/strong):/compact 丢决策/路径,撞上限直接"Conversation too long"被迫 /clear。claude-code #26317
- **压缩前快照**(mcp/strong):auto-compaction 有损,把"删前先验证"硬约束丢掉致误删生产库;PreCompact hook 只能 stderr 不能 act。#15923 #34299 #43733 #43946(#7530 200+评论)
- **规则保鲜器**(skill/medium):CLAUDE.md 3 个月堆 400 行,加规则反降遵守(模型可靠遵守约 150-200 条)。claude-code #22022

### C. 验证 / 质量门(防"假装完成")
- **完成度验真 / 可验收闭环**(skill/strong):agent 不跑就说 done;某交易系统"14400 tests all green while real money bled"。claude-code #14947 #12369 #37818
- **Agent自验QA**(mcp/strong):团队真实做法"We just run it and hope";TDAD(arxiv 2603.17973)证依赖图作 skill 把解决率 24%→32%
- **独立审查官**(skill/strong):同会话审自己代码无脑批准"implementation looks excellent",队友挑出 3 个 critical bug
- **回归影响图**(skill/medium):agent 改一处 break 旧测试,commit 前不知该跑哪些。TDAD:光给 TDD 指令不给测试上下文反把 regression 推到 9.94% 比不干预差
- **AI审查降噪**(skill/medium):30 行 PR 给 8-15 条评论,有用 2-3 条;false positive 是头号抱怨
- **引证核验器**(skill/strong):报告 11%-57% 引用是编造;CiteME 基准前沿 LLM 4-18% 引用归因准确。arxiv CiteAudit 2602.23452

### D. 可靠工具调用 / 结构化输出
- **工具调用守门员**(mcp/strong):参数/JSON 不合规触发无限 retry loop;加 schema 校验错误率 5%→<0.3%、multi-step 准确率 10%→70%
- **输出契约器**(skill/medium):Claude/开源模型无 strict-mode,structured output 失败率 2-10%;跨模型 schema 强约束 + error-type-aware 重试。JSONSchemaBench
- **确定性数据闸**(skill/medium):丢 CSV 让 agent 算→付钱让模型做它最差的算术,每次答案不一样;"Blueprint First, Model Second"Pass^1 +10.1 个百分点。langchain #2581
- **文档表格抽取**(mcp/medium):PDF/Excel 合并单元格、多级表头、跨页表格全崩,坏 chunk 喂坏 RAG。ParseBench arxiv 2604.08538

### E. MCP 安全(全生态系统性短板)
- **MCP鉴权脚手架**(mcp/strong):正经鉴权"每组件一周",53% 用静态 key 仅 8.5% OAuth;一键套鉴权+按工具授权+绑 127.0.0.1。dev.to 88% 无鉴权
- **STDIO安全闸**(skill/medium):36.7% SSRF / 41% 无鉴权;OX Security 2026-04 STDIO 即使启动失败也执行命令,20万+实例可注入;Atlassian server CVE 9.1
- **工具投毒盾**(mcp/strong):tool response 直接进 context 无检查,藏指令致 agent 导出整个 WhatsApp;rug pull、跨工具投毒。OWASP 已收录,MCPTox 测 353 真实 tool

### F. MCP/Skill 工程脚手架(给 agent 工具的作者用)
- **MCP脚手架**(mcp/medium):从零写生产级 MCP 像接微服务;OAuth 2.1+PKCE+双 transport+分页 boilerplate 反复绊人
- **Agent级Eval器 / Agent工具调用评测**(mcp/strong+medium):官方 Inspector 只验 tool 做什么、不验 agent 多轮里怎么用;40% 已部署 server 至少一个工具坏。arxiv 2509.09734 MCP-AgentBench
- **技能预加载器**(skill/medium):refs/*.md 必须运行时显式 Read,每次多一轮 round trip。anthropics/skills #1220
- **团队技能同步器**(mcp/medium):skills 每机一份,团队 5 人手动 re-sync,submodule 崩、dotfiles drift。anthropics/skills #1132
- **跨平台技能体检**(skill/medium):skill 引用平台没有的工具静默失败(Write 覆盖 vs create_file 报错)。anthropics/skills #1154
- **Slop-PR守门**(skill/medium):anthropics/skills 两周 46 PR 有 5 个 slop;anti-slop 已在 Coolify 月挡 120 个。#1133
- **任务专精agent生成**(skill/weak):agent-creator 定义角色+白名单挑 skill 子集。anthropics/skills #1119(暂无 reaction)

### G. 多 agent 协同(Tony smux/team 编排痛点)
- **子代理MCP桥**(mcp/medium):Claude Code subagent 拿不到 MCP tools,只有内置工具,specialized worker 形同虚设。claude-code #34935、copilot-cli #693
- **多agent契约对齐**(skill/medium):subagent 不能直接通信,handoff 经主 agent 转述丢 response shape/API schema。charlesjones.dev
- **子代理交接桥**(skill/medium):SubagentStop hook 写临时状态文件 + UserPromptSubmit 读回,官方自称"fragile"。claude-code #5812

### H. 运维 / 可观测
- **Token账单溯源 / 成本归因器**(mcp/strong+medium):账单只给总数不给原因;agent 比 chatbot 烧 5-30 倍 token;Uber 4 个月烧光全年预算。微软修复建议竟是"关掉 evaluator"
- **用法/计费防呆**(skill/medium):rate limit 任务中途触顶锁人;临界自动降模型/排队/通知
- **调度防呆器**(mcp/medium):cron/webhook 接 agent 真正炸的是重叠运行、失控成本($500+/夜)、无 audit。Task Trigger MCP 已验证需求。**Tony launchd 重度用户正中**

### I. 垂直 / 其他
- **文件读图读PDF**(mcp/strong):官方 Filesystem MCP read_file 只读文本,遇 PNG 退化。modelcontextprotocol/servers #533 top open issue
- **合同律法MCP**(mcp/medium):legal/CLM 是 MCP 明确空白,无 agent 读合同/义务抽取/redline
- **浏览器抓取兜底**(mcp/medium):纯 Playwright 选择器 30 天 15-25% 需修,纯 AI flaky+贵;分层兜底
- **日志直喂手**(mcp/medium):反复手抄 50 行报错粘进 agent;Cursor 粘 debug console 后 agent 看不到
- **评审回信员**(mcp/medium):PR 评审后逐条人工回应耗时;agent 监听线程+读 diff+自动改+答辩
