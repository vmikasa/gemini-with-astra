# Gemini with Astra · 基于 v0.2.1 的本地开发版

在同一个 Git 项目里，你可以和 Gemini 谈清需求，让 Astra 实现，再请 Gemini 从实际使用者的角度验收。也可以直接找 Astra 质疑方案，或新开一个聊天独立做小事。交给已有 Astra 主会话时，按地址投递，由你切换 CLI。只需第二份技术判断时，Gemini 可以按你的选择另开全新的只读 Worker，你继续讨论，按需取回审查原文。[后台审查示例](COLLABORATION-GUIDE.md#worker)

**第一次使用**，先按下文安装并启用。**已经装好，想知道眼前的事怎么做**，直接看[《人与 Agent 协作场景手册》](COLLABORATION-GUIDE.md)。手册有可复制的对话，包括需求还很模糊、两个 Codex 并行、科研复现、盲审、返工、恢复旧工作和处理历史消息。

两个 Agent 都可以发起任务、质疑前提和提出方案。如何在交接时保住这种独立性，以及用户如何直接听到双方的意见，见[《协作设计哲学》](DESIGN-PHILOSOPHY.md)。

| 谁 | 通常关注什么 | 谁做决定 |
| --- | --- | --- |
| GEMINI · Antigravity CLI（`agy`） | 发现真实意图、澄清需求、发散探索、界面与交互体验，检查交付是否解决了原问题 | 可以实现、审查，也可以质疑指标 |
| ASTRA · Codex CLI | 复杂推理、架构、算法、工程实现、排错和客观验证 | 可以提出产品方案、挑战目标，也可以独立完成任务 |
| 你 | 选择这次聊天可以读哪些背景，决定何时邀请另一方，确认重要取舍和最终效果 | 已指定的 Owner 和 Reviewer 优先；日常分工可交给 Agent |

协作身份取决于当前 CLI。同一 CLI 内换模型会保留身份。v0.2.0 把旧版两只按身份共用的邮箱改为按 Session、Task 和 Workstream 投递，一台机器上可以同时有多扇 Astra 或 Gemini 窗口。

## 安装到两个 CLI

准备 Git 和 Python 3.9+。Git 需支持 `git rev-parse --path-format=absolute` 及 `git worktree list --porcelain -z`。在任一已有 CLI 中，复制整段交给 Agent。

```text
使用本地开发版时，以当前工作副本为来源，记录其提交号，检查 scripts/astra_worker.py 是否存在（位于 Skill 目录内）。若指定安装已发布的 v0.2.1 标签，请从 https://github.com/vmikasa/gemini-with-astra 取得该标签；该标签提供主会话交接。
在临时目录检查 skills/gemini-with-astra/，根部应直接有 SKILL.md 和 LICENSE，
并有 agents/、assets/、scripts/。把这一份分别安装到
Codex CLI 的 ~/.agents/skills/gemini-with-astra/
和 Antigravity CLI 的 ~/.gemini/config/skills/gemini-with-astra/。
先比较已有副本。完全相同就保留，有差异就列出路径与版本，等我确认备份和覆盖。
按相对路径和逐文件 SHA256 比较来源及两份安装。仓库 README、使用手册和 tests/ 留在安装目录外。
这一步只安装 Skill，不初始化或升级项目，也不改用户级规则或 CLI 配置。
```

安装后分别开一个新聊天，验证 Skill 发现。这里只需要读取 Skill 自身的说明。

v0.2.1 更新了交接模板和验收记录措辞，项目状态文件沿用 v0.2.0 格式。更新 Skill 安装目录只会更新供以后生成的模板和脚本。已经初始化的项目继续使用项目内的副本。需要在旧项目采用新措辞时，请 Agent 先只读比较已生成的常驻规则、协议和协调脚本，保留项目定制后再决定是否同步。

| 在哪里发 | 复制这句话 |
| --- | --- |
| Codex | `$gemini-with-astra 只读报告这份 Skill 的名称、版本，以及 L1/L2/L3 分别适合什么情况。不要执行脚本。` |
| Antigravity | `/gemini-with-astra 只读报告这份 Skill 的名称、版本，以及 L1/L2/L3 分别适合什么情况。不要执行脚本。` |

## 为一个项目启用一次

在目标仓库的**主工作副本**中，从任一端初始化一次。两个 CLI 若使用同一份工作目录，第二端只需新开聊天验证规则。日常协作可直接用自然语言。

| 你的情况 | 选择 | 文件与 Git 的关系 |
| --- | --- | --- |
| 自己在本机做任务，希望协作材料留在自己的工作副本 | `local` | 协议和长期文档在 `.ai/docs/`。通常使用本地排除的根 `AGENTS.md`；如有既有规则冲突，可单独批准仅针对该仓库的桥接。 |
| 希望把协作规则、规格和决策随代码提交，方便克隆和交接 | `private` | 规则在根目录，协议、辅助脚本和长期文档在 `docs/`。你选择何时提交。会话、投递、工作中任务和检查点仍在 Git 忽略的 `.ai/`。 |

两种模式都能单人或双 Agent 工作，都可用于没有 GitHub 远端的仓库。模式名称不决定 GitHub 仓库的可见性。

```text
$gemini-with-astra 用 local 模式为当前主工作副本启用协作。保留原有规则和未提交修改。
如果需要写用户级桥接，先说明确切文件和原因，等我同意。
完成后报告静态检查结果，给我新聊天验证用的探针和预期激活码。
```

换到 agy，把前缀改为 `/gemini-with-astra`。要版本化规则，把模式改为 `private`。**初始化输出的预期激活码留给自己核对。** 在同一目录的两个新聊天里各发一次下面这段；两端独立说出正确的码，才说明各自这次聊天加载到了项目规则。

```text
仅依据本次聊天已加载的项目规则，报告 Activation code、规则来源和跨 Agent 派单条件。
若已加载的桥接规则明确指定常驻文件，可以直接读取该文件。
不要搜索项目、调用 Skill 或修改文件。没有加载就回答 NOT_LOADED。
```

## 每个新聊天，先选一次上下文

| 第一条消息可以这样写 | 可用背景 | 适合的工作 |
| --- | --- | --- |
| “L1，只用项目背景，修正导出按钮的提示文案。” | 相关源码、项目材料、已确认的 SPEC 和 DECISIONS。跳过任务、会话、收件箱以及未读计数。 | 独立小改动；普通工作无需注册 |
| “L2 T001 / WS-UI，先只读核对这个工作流的验收条件。” | 指定任务与相关工作流；已登记的本会话只取相应范围的投递。无任务归属的通知继续待处理。 | 接手已知任务、定位问题、同伴评审 |
| “L3，从 C-A001 恢复 T001 / WS-UI 的检查点。先只读。” | 所选前任与切片；存在多个切片时，可先只列标识再选。 | 中断后接续；继续参与时注册新的 Session，转移旧责任需另行授权 |

编号只是例子，请换成 Agent 实际返回的值。每个新聊天独立选择。已经读进一个聊天的内容会留在历史里，需要真正独立判断时请新开聊天。上下文级别与代码写权限分别选择；L1 可以按你的授权改代码，L2、L3 都可以严格只读。

### 第一次实际交接

1. **在 Gemini 澄清。** “L1。帮我明确账单页 CSV 应导出哪些行、金额如何显示、空结果怎么办。先把要我决定的问题列出来。” 你确认后再发起协作。
2. **取得接收地址。** 使用初始化后已加载常驻规则的目标 Codex 聊天；早已打开的聊天先显式重读项目入口，或另开新聊天。在目标窗口说“这次只办理可写的接收地址登记。为新任务登记一个 ASTRA Session，只告诉我公开 ID，等我给任务号再读。” 把这个短 ID 告诉发起方即可，长句柄留在它自己的聊天中。
3. **在 Gemini 派单。** “我确认只导出筛选结果、金额两位小数、空结果只保留表头。把我的原话、输入样例和这三个条件写进共同契约，指定刚登记的 Astra 为 Owner，你负责审查。你建议复用页面表格的格式化器，就把理由另发为‘Gemini 候选’，由 Astra 验证和选型。给我任务编号。”
4. **切回原 Codex 聊天。** “L2 T001。按契约实现，并用三个具体输入验证。记录代码版本或工作区指纹、输出样例和测试结果。” 用上一步拿到的实际编号。
5. **回到 Gemini。** “L2 T001。先盲读契约，独立导出并比较结果，再看 Owner 的 Result。给我一份实际 CSV，并分别列出你和 Astra 的重要判断。” 三个条件都通过时，写“Reviewer Gemini 按契约通过”，附受检版本。你亲自打开文件并明确接受后，再记“用户确认该版本的导出结果”，附原话或出处。只有前一项时就只报前一项。

**反向派单同样成立。** 你可以对 Astra 说：“我确认键盘用户必须能发现并恢复导出失败。把原话、复现步骤和焦点轨迹交给指定的 Gemini。你建议用弹窗，请另署名为‘Astra 候选’，由 Gemini 判断行内提示是否更合适。交付后你验证键盘路径，我来试用。”需要两份独立判断时，只先交付相同的问题、证据和硬约束，等用户要求揭示后再交换候选。[双向派单示例](COLLABORATION-GUIDE.md#handoff)

## 已有 v0.1.1 项目如何升级

装上新版 Skill 后，旧项目仍保留旧常驻规则。请在旧项目的主工作副本里**先预览**。

```text
$gemini-with-astra 对当前 v0.1.1 项目运行只读升级预览，报告规则漂移、原邮箱、备份位置和计划更新的文件。
先停在预览。等我确认旧版会话已停止写入并批准后，再应用升级并核对静态诊断。
保留旧任务和两份 to-*.md 原文。未确定去向的消息留在 Legacy Pending。
```

已确认某条旧消息属于 T001，只能据此归类。等你确定具体 Session 或明确要求面向该任务广播，再投递。仅有旧规则、缺少本机 manifest 的克隆需要先诊断来源。处理示例见[手册的升级与异常恢复部分](COLLABORATION-GUIDE.md#maintenance)。

## 初始化与正式运行后的文件

刚初始化时会有项目规则入口、协议、两个辅助脚本、本机清单、锁及 Git 排除项。下图把两种模式放在一起；其余文件在用到相关功能后才出现。日常让 Agent 通过项目协调工具按范围读取即可。

```text
主工作副本/
├── AGENTS.md                         两端的常驻规则；local 桥接时入口正文在 .ai/AGENTS.md
├── AGENTS.override.md                private 遇到已有非空覆盖文件时也补充规则
├── .gitignore                        private 在这里排除 /.ai/；local 使用 Git 的 info/exclude
├── docs/                             下面五个文件在 local 模式位于 .ai/docs/
│   ├── DUAL-COLLAB.md                派单、检查点、评审与消息协议
│   ├── dual-collab.py                协调工具，负责按范围读取与受控写入
│   ├── astra_worker.py               异步只读审查的本地后台进程
│   ├── dual-collab-snapshot.py       计算未提交 Git 工作状态指纹
│   ├── SPEC.md                       已确认、当前有效的长期规格（按需）
│   └── DECISIONS.md                  已批准的取舍、理由和依据（按需）
└── .ai/
    ├── dual-collab.json              初始化模式、代码根、激活码及静态校验清单
    ├── runtime-v2.lock               本地协作进程锁
    ├── worker-reviews/               首次派 Worker 时创建，按 Gemini、任务及工作流保存作业及原文
    ├── runtime-v2.transaction        正在提交或等待恢复的写入批次
    ├── sessions/C-A001/
    │   ├── SESSION.md                宿主、开放状态、前任和私有句柄哈希
    │   ├── checkpoints/              PROJECT.md、T001.md、T001~WS-UI.md 等独立切片
    │   └── transfers/                接管的范围、版本及移交投递记录
    ├── tasks/
    │   ├── T001.md                   主契约、直接成员、Owner、Reviewer、结果及评审
    │   └── T001/
    │       ├── workstreams/WS-UI.md  子工作流的契约、成员、版本与交付
    │       └── history/              契约修订前的版本
    ├── sync/
    │   ├── sends/M-….json            发件快照，关联逻辑消息与逐人投递 ID
    │   ├── inboxes/C-A001/           当前地址的待办，按 PROJECT、T001、T001~WS-UI 等分目录
    │   └── receipts/C-A001/D-….json  单个投递的处理证据或转交去向
    ├── workspaces/                   已附着代码目录；writers/ 记录正在写入的会话
    ├── explore/E001/                 共同 brief.md 和独立的 gemini.md、astra.md
    ├── upgrades/0.1.1-to-0.2.0/      升级计划、original/ 原始文件备份和完成标记
    └── legacy/                       pending/ 冻结旧邮箱；classified/ 归类；resolved/ 已处理区间；
                                      task-backups/ 保存正式接纳的旧任务原文
```

升级过的项目还可能有 `.ai/sync/to-astra.md` 和 `to-gemini.md` 作为迁移来源。工作中的正文按接收者分别确认；一位处理完不会清空另一位的待办。`private` 模式下已提交的规则与设计文档可以跨机器携带，活动 Session 和未处理投递仍在原机器。严格只读约束适用于协调工具，工作区文件仍受本地账户权限控制。

## 开发与验证

[Skill 入口](skills/gemini-with-astra/SKILL.md) · [运行协议](skills/gemini-with-astra/assets/PROTOCOL.md) · [使用场景手册](COLLABORATION-GUIDE.md) · [MIT 许可证](LICENSE)

在仓库根目录运行 `python -B -X utf8 -m unittest discover -s tests -v`。除了 v0.2.1 的 41 项回归，[Worker 测试](tests/test_worker.py)覆盖派单选择、重复提交、权限范围、进度、失败与原文回传。[运行时测试](tests/test_runtime.py)检查实际读取范围、广播快照、并发与中断恢复；[迁移测试](tests/test_upgrade.py)使用取自公开版提交 [24a1378](https://github.com/vmikasa/gemini-with-astra/commit/24a13785a1becf50796cc0b4c69f04bbd89aa6d7) 的原始文件夹具，覆盖旧项目与旧邮箱。

本版发布验证使用 Windows 11 的临时项目。自动化测试中的 linked worktree 使用模拟目录和 Git 响应。Windows 10、两个真实订阅 CLI 在新聊天里的首轮行为，以及实际 worktree 中双端加载规则，需要在对应环境分别验证。
