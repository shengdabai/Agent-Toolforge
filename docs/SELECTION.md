# 选定的 10 个产品(2026-06-05,Tony 授权按画像+市场挑)

| slug | 中文 | 形态 | 石头# | 信号 | 需求填空(什么人/场景/价值/痛) |
|---|---|---|---|---|---|
| mcp-slim-proxy | 瘦身代理 | MCP | ① | strong | 挂多 MCP 的 agent 重度用户,一调用就 context 爆,省 90%+ token/账单 |
| agent-memory-core | 记忆脑 | MCP | ⑤ | strong | 跑长/多天任务的 agent,新会话清零反复重述,省重建上下文的 15-30 分钟 |
| checkpoint-resume | 断点续跑 | Skill | ⑥ | strong | 跑多步批处理的 indie dev,第 201 个崩从头来,省整轮重跑 |
| verify-done | 完成度验真 | Skill | ⑩ | strong | solo dev 没人 review,agent 不跑就说 done,避免假完成上生产 |
| fresh-eyes-review | 独立审查官 | Skill | ⑫ | strong | agent 写完想要质量门,同会话自审无脑批准,挡 critical bug |
| citation-verifier | 引证核验 | Skill | ⑮ | strong | 出报告/研究的 agent,11-57% 引用造假,保住可信度 |
| toolcall-guard | 工具守门员 | MCP | ⑯ | strong | 自建/小模型 tool-calling,参数不合规无限 retry,错误 5%→<0.3% |
| token-ledger | 账单溯源 | MCP | ㉝ | strong | 跑多 agent 的团队,账单只给总数,定位哪个会话烧钱 |
| cron-guard | 调度防呆 | Skill | ㉟ | medium | launchd/cron 跑 agent,重叠运行+失控成本+无 audit |
| multimodal-fs | 读图读PDF | MCP | ㊱ | strong | 用 Filesystem MCP 的 agent,read_file 遇图/PDF 退化 |

## MVP 原则(每个都要满足)
- 核心逻辑做成纯模块 + 真实测试(TDD),即使 MCP runtime 装不上,逻辑测试也能绿
- MCP server = 薄 wrapper 套在纯逻辑上;Skill = SKILL.md + 可选 helper 脚本 + smoke test
- 最小依赖,优先 stdlib;每个产品自带 README + SPEC + 测试命令
- 对外发布:无真名/学员/Tony 私有项目名,英文命名
