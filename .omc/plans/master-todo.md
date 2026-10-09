# Agent Toolforge — 10 个面向 agent 的产品服务

> 决策(2026-06-05 office-hour 问答确定):
> - **形态**:混合(技能 Skill + MCP server,逐产品判断最合适形态)
> - **点子来源**:翻石头扫机会(刘小排铁律:我只搬石头堆,需求由 Tony 自己挑/填)
> - **MVP 深度**:可运行 + 真实测试(TDD + smoke test)
> - **用途**:对外发布(需脱敏 / 规范打包 / 可发 GitHub-marketplace)
> - 项目根:`~/Desktop/项目开发/agent-toolforge/`
> - 编排:已显式授权 Workflow 多 agent 并行

## Phase 0 — 翻石头(research)
- [x] R1: 多源并行扫(6 角度/71万 token/81 次联网),44 块候选石头 → `research/stone-pile.md`
- [x] R2: Tony 授权按画像+市场代选,定 10 个 → `docs/SELECTION.md`(5 MCP + 5 Skill)

## Phase 1+2 — 设计+构建(Workflow 并行,Tony 授权 pick+develop 直造)
选定:mcp-slim-proxy / agent-memory-core / checkpoint-resume / verify-done / fresh-eyes-review / citation-verifier / toolcall-guard / token-ledger / cron-guard / multimodal-fs
- [x] B1..B10: 10 个产品并行 spec→TDD→独立验证,全部 verdict=pass(20 agent)
- [x] V: 独立 verify agent 复跑 10/10 绿 + 主会话全量复验 10/10 OK

## Phase 3 — 脱敏 + 打包发布(对外)
- [x] P1: secret scan ✓无密钥 / 脱敏 ✓无真名·学员·私有项目名(ASCII+中文) / 清 .pyc(含 username 泄露)+ .gitignore
- [x] P2: 顶层 marketplace README + 每产品 SPEC/README/SKILL.md/tests 齐
- [x] P3: 多维 review = 独立 verify(10/10)+ 全量复测 + 脱敏扫 + 文档微瑕修复

## 状态
- 全部完成。git 未 commit(待 Tony 决定);发布命令见下方汇报。
