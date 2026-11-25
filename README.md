# Gemini with Astra

让 Gemini 和 Codex 在同一个 Git 仓库里接力工作。你可以在 Gemini 里把需求谈清楚，切到 Codex 实现，再回到 Gemini 验收。两边通过项目里的任务记录共享目标、约束和结果。你负责切换 CLI、决定重要取舍，也可以让同一个 Agent 独立完成整项工作。

**ASTRA** 是 Codex CLI 中的协作身份，通常侧重架构、算法、工程实现和技术验证。**GEMINI** 是 Antigravity CLI（`agy`）中的协作身份，通常侧重需求澄清、方案探索、视觉与交互体验。在同一 CLI 中换模型会保留身份。任一方都可以承担实现或审查。

## 一、把这段发给 Agent 安装

准备好 Git、Python 3.9+，以及能正常使用的 Codex CLI 和 Antigravity CLI。Skill 脚本只用 Python 标准库。在任意一端发送下面的提示词，安装一次即可供个人的多个项目使用。

```text
请从 https://github.com/vmikasa/gemini-with-astra 安装 gemini-with-astra。
在临时目录获取仓库，记录本次使用的 Git 提交号。只取 skills/gemini-with-astra/ 这一层，
它的根目录里应当直接有 SKILL.md。将这一份分别安装到当前用户的两个目录：

Codex CLI：~/.agents/skills/gemini-with-astra/
Antigravity CLI：~/.gemini/config/skills/gemini-with-astra/

先检查两个目标。已有副本与来源相同就保留；有差异就先告诉我，等我决定是否覆盖。
完成后，用相对路径和逐文件 SHA256 核对来源及两份安装，报告结果。
这一步只安装 Skill，不初始化项目，不改全局规则或 CLI 配置。
```

安装好后，各开一个新会话。分别发送下面对应的一行，确认两个 CLI 都能显式调用 Skill。

| 在哪里发 | 复制这条提示词 |
| --- | --- |
| Codex CLI | `$gemini-with-astra 只读取这份 Skill 的说明，告诉我它的名称，以及 setup.py 和 snapshot.py 各自做什么。不要运行脚本或写文件。` |
| Antigravity CLI | `/gemini-with-astra 只读取这份 Skill 的说明，告诉我它的名称，以及 setup.py 和 snapshot.py 各自做什么。不要运行脚本或写文件。` |

如果没有出现，先在 Codex 中输入 `/skills` 查找名称，在 Antigravity 中输入 `/skills reload` 刷新后再试。预期能看到 `gemini-with-astra`，并得到两个脚本的用途：前者初始化或诊断项目，后者计算 Git 可见工作状态的指纹。[Codex Skills](https://developers.openai.com/codex/skills) · [Antigravity Skills](https://antigravity.google/docs/skills)

## 二、为一个项目启用协作

在要协作的 **Git 仓库根目录**打开任意一端。每个项目只需初始化一次，两端都在同一份工作目录里使用它。

### 如何选择模式

**只在这台电脑处理自己的任务，想让两端下次接着做，选 `local`。** 关闭 CLI 后，规则、任务和决定仍保存在当前工作目录。**如果是自己长期维护的项目，想用 Git 保存规则和设计决定，将来在另一台电脑上继续，选 `private`。** 即使只有你一个人开发，这也是选 `private` 的充分理由。

| 你关心的问题 | `local` | `private` |
| --- | --- | --- |
| 长期规则与文档放在哪？ | 常驻规则通常在根目录 `AGENTS.md`，协议和长期文档在 `.ai/docs/`，都只保存在当前工作副本。 | 常驻规则在根目录 `AGENTS.md`，协议和长期文档在 `docs/`，可以与代码一起提交。 |
| 初始化后 Git 会看到什么？ | 本地排除规则写入 `.git/info/exclude`。成功初始化后，原有 Git 工作区状态保持不变。 | 根目录 `.gitignore` 会加入 `/.ai/`。规则、协议和辅助脚本会出现在 Git 变更中，由你决定何时提交。 |
| 换电脑重新克隆后能拿到什么？ | Git 克隆只带走仓库中已提交的内容，本机协作资料留在原工作副本。 | 提交并推送过的规则、协议和设计文档可以随仓库取回。任务单、同步消息和初始化清单仍留在原机的 `.ai/`。 |

两种模式都支持双端派单和验收，都可以在没有 GitHub 远端的本地 Git 仓库使用。代码是否提交、是否推送以及仓库可见性均由你决定。已经初始化过的项目会保留原来的模式。

### 初始化与验证

**例如，在 Codex 启用可随仓库提交的规则：**

```text
$gemini-with-astra 用 private 模式为当前 Git 仓库初始化协作。
保留已有规则和未提交修改。完成后报告静态检查结果，并给我两端验证用的探针。
```

**或者，在 Antigravity 启用仅限本机的协作：**

```text
/gemini-with-astra 用 local 模式为当前 Git 仓库初始化协作。
如果需要用户级规则桥接，先列出文件及用途，等我同意。完成后给我验证探针。
```

两个 CLI 都支持两种模式。把第一行换成对应 CLI 的调用名和你想用的模式即可。

**确认项目规则已加载。** 初始化会输出预期的 activation code。在同一仓库根目录分别新开 Codex 和 Antigravity 会话，向两边各发一次下面的提示词，保留预期 code 给自己核对。两边报告的 code 都匹配、也能解释派单条件，说明两端在这次会话中读到了项目规则。

```text
请仅根据本次会话自动加载的项目规则，报告 Activation code、规则来源，以及何时应跨 Agent 派单。
若已加载的桥接规则明确指定常驻文件，可以直接读取该文件。
不要搜索项目、调用 Skill 或修改文件。没有加载就回答 NOT_LOADED。
```

### 初始化后会生成哪些文件

下面只列与 Skill 有关的路径。两棵目录树展示的是**刚初始化成功时**的典型布局。

**选择 `local`，且根目录没有既有规则冲突时**

```text
项目根目录/
├── AGENTS.md                     # 本机两端读取的常驻规则，已在本地排除
├── .ai/
│   ├── dual-collab.json          # 本机初始化清单，记录模式、路径和静态检查数据
│   └── docs/
│       ├── DUAL-COLLAB.md        # 交接、实现、审查和同步协议
│       └── dual-collab-snapshot.py  # 核对未提交工作状态的只读指纹工具
└── .git/info/exclude             # 在此追加本仓库的本地排除规则
```

如果已有根规则需要保留，`local` 会先列出桥接需要的用户级文件。经你单独同意后，常驻规则改放在 `.ai/AGENTS.md`，原有根规则保留。Codex 的用户级规则和 Antigravity 的用户级规则会增加一个仅指向当前仓库的入口。

**选择 `private` 时**

```text
项目根目录/
├── AGENTS.md                     # 项目常驻规则，可以提交
├── .gitignore                    # 在此追加 /.ai/
├── docs/
│   ├── DUAL-COLLAB.md            # 可以提交的协作协议
│   └── dual-collab-snapshot.py   # 可以提交的只读指纹工具
└── .ai/
    └── dual-collab.json          # 本机初始化清单，由 Git 忽略
```

已有的 `AGENTS.md` 会保留原文并追加协作规则。如果根目录已有非空的 `AGENTS.override.md`，脚本也会在其中追加规则，以便使用该覆盖文件的 Codex 会话能读到规则。

任务单、设计规格和收件箱会在协作中按需出现。要查派单以后去哪里看进度、验收结果或另一方的方案，可直接跳到[正式运行后的完整目录树](#正式运行后的完整目录树)和[逐文件说明](#每个文件怎么用)。

## 三、实际走一遍：从需求到验收

下面三条可以直接复制。两个 CLI 都打开**同一份工作目录**。启用后，日常消息直接用自然语言，无需再加 Skill 名称。

**① 在 Gemini 里谈好需求，发出任务。**

```text
我要给账单页加 CSV 导出。只导出当前筛选结果、金额固定两位小数、空结果只输出表头。
这些是已确认需求。把这项工作交给 Astra 实现，由 Gemini 验收。
把约束和可检查的完成条件写进任务，并告诉我任务编号。
```

Gemini 会给出类似 `T001` 的编号，在 `.ai/tasks/` 中留下契约。你现在切到 Codex。下两条里的 `T001` 换成实际编号。

**② 在 Codex 里接手并实现。**

```text
执行 Gemini 刚交给你的 T001。先读任务契约，保留已有工作区修改。
实现后验证这三个导出场景，在 Result 里记录改了什么、如何验证、交付对应哪份代码。
```

Codex 在任务的 `Result` 留下证据。状态 `IMPLEMENTED` 表示可供验收。这时可以切回 Gemini，即使代码尚未提交也可以审查实际改动。

**③ 回到 Gemini，对照用户场景验收。**

```text
验收 T001。先对照契约检查实际改动与导出结果，再看 Result。
逐项核对筛选范围、金额精度、空结果表头，把结论写进 Review。
如果需要返工，给 Astra 一个能复查的具体例子。
```

发现问题时，在 Codex 说“按 T001 的 Review 返工，补充验证并更新 Result”。通过时，审查方把结论绑定到实际验证过的代码和契约版本。用户保留最终验收决定权。

### 其他常用提示词

| 想做什么 | 发给谁 | 提示词 |
| --- | --- | --- |
| 做一个小改动 | 任一端 | “把导出按钮移到筛选栏右侧，直接修改并验证。” |
| 比较独立方案 | 先发给任一端，再按提示切换 | “为离线同步建立共同 brief。你们各自提出方案，先不要读对方的版本，等我说可以再互评。” |
| 通知已批准的变化 | 正和你讨论的一端 | “刚才我确认金额改成按币种精度显示。更新相关任务和已批准的决定，通知另一端哪些验收项受影响。” |
| 中断后接续 | 要接手的一端 | “恢复这个仓库里分配给你的未完成任务，读相关同步和任务记录，告诉我上次停在哪里。” |
| 只诊断项目 | Codex 或 Antigravity | “请显式使用 gemini-with-astra，只做 status 诊断，报告缺失、冲突和规则漂移，不做修复或初始化。” 在 CLI 中分别用 `$gemini-with-astra` 或 `/gemini-with-astra` 选中 Skill。 |

用户指定的 Owner 和 Reviewer 优先，其余角色由 Agent 依任务选择。已有归属的任务改派须经用户同意。独立审查价值有限时可以使用 `Reviewer: none`。写入任务或同步消息后，由你切换 CLI，两端默认轮流写同一工作目录。

## 正式运行后的完整目录树

以账单 CSV 导出为例，假设双方已做过一轮独立设计，用户选定了方案，Astra 完成了任务，Gemini 写了验收结论，双方也交换过同步消息。下面分别展示两种模式下与这次协作有关的文件。功能代码和测试仍在项目原有目录中。

**`local` 模式：个人在同一工作目录持续协作**

```text
项目根目录/
├── AGENTS.md                         # 本机常驻规则入口
├── .git/info/exclude                 # 本仓库的 Git 本地排除规则
└── .ai/
    ├── dual-collab.json              # 初始化清单与诊断依据
    ├── docs/
    │   ├── DUAL-COLLAB.md            # 协作协议
    │   ├── dual-collab-snapshot.py   # 未提交工作状态的指纹工具
    │   ├── SPEC.md                   # 当前已确认的设计
    │   └── DECISIONS.md              # 重要决定及其理由
    ├── explore/
    │   └── E001/
    │       ├── brief.md              # 两边共用的题目与约束
    │       ├── gemini.md             # Gemini 的独立方案
    │       └── astra.md              # Astra 的独立方案
    ├── tasks/
    │   └── T001.md                   # 同一任务的契约、实现结果和验收记录
    └── sync/
        ├── to-astra.md               # 发给 Astra 的消息
        └── to-gemini.md              # 发给 Gemini 的消息
```

**`private` 模式：长期规则和设计文档可随代码提交**

```text
项目根目录/
├── AGENTS.md                         # 项目常驻规则入口
├── AGENTS.override.md                # 可选，仅已有非空覆盖文件时补充规则
├── .gitignore                        # 将 /.ai/ 排除在 Git 之外
├── docs/
│   ├── DUAL-COLLAB.md
│   ├── dual-collab-snapshot.py
│   ├── SPEC.md
│   └── DECISIONS.md
└── .ai/
    ├── dual-collab.json
    ├── explore/
    │   └── E001/
    │       ├── brief.md
    │       ├── gemini.md
    │       └── astra.md
    ├── tasks/
    │   └── T001.md
    └── sync/
        ├── to-astra.md
        └── to-gemini.md
```

两棵树展示了各项功能都用过的例子。一次普通交接可能只有 `T001.md`，两端直接通过任务单就能完成实施和验收。后续任务使用 `T002.md` 等新编号。独立探索有自己的编号，例如 `E002/`，一次探索与一项任务可以分别创建。同步消息处理后，收件箱也可能为空。

**`local` 遇到既有根规则时**，如果用户同意使用桥接，原来的根规则保留，Skill 的常驻规则位于 `.ai/AGENTS.md`，其余协作文件与上面的 `local` 树相同。两份额外入口在项目目录外：Codex 使用其个人规则目录下生效的 `AGENTS.md` 或 `AGENTS.override.md`，Antigravity 使用 `~/.gemini/config/rules/dual-collab-<code>.md`。它们的用途都是在打开这个仓库时，引导对应 CLI 读取 `.ai/AGENTS.md`。

### 每个文件怎么用

下表中的 `DUAL-COLLAB.md`、`dual-collab-snapshot.py`、`SPEC.md`、`DECISIONS.md` 共用一个目录。在 `local` 模式下去 `.ai/docs/` 找，在 `private` 模式下去 `docs/` 找。

| 文件 | 谁写、何时产生 | 什么时候读、读什么 |
| --- | --- | --- |
| `AGENTS.md` | 初始化脚本写入常驻规则。使用本地桥接时，这份规则写在 `.ai/AGENTS.md`。 | 两端进入项目时读取。这里规定如何识别身份、何时打开协议、何时查看自己的收件箱。 |
| `AGENTS.override.md` | `private` 初始化时，脚本会在已有的非空覆盖文件中补充规则。 | Codex 优先采用该覆盖文件时，仍能从这里读到项目的协作入口。 |
| `.git/info/exclude` | `local` 初始化时追加本机排除项。 | Git 据此忽略本地协作资料。想核对为何 `git status` 看不到它们时，看这里。 |
| `.gitignore` | `private` 初始化时追加 `/.ai/`。 | Git 据此忽略任务、消息和初始化清单。这条排除规则可以随仓库提交。 |
| `.ai/dual-collab.json` | 初始化脚本生成，记录模式、仓库路径、激活码和文件检查信息。 | 运行 `status` 时，脚本用它检查入口、文件内容和 Git 排除规则。任务进度记在任务单里。 |
| `DUAL-COLLAB.md` | 初始化脚本从 Skill 模板生成。 | Agent 在派单、独立探索、正式审查或恢复工作时，按需查阅具体流程。 |
| `dual-collab-snapshot.py` | 初始化时复制到项目。 | 改动尚未提交时，实施方可运行它，把输出的工作状态指纹记入 Result。审查方可再次运行，核对看到的是否仍是同一份改动。 |
| `SPEC.md` | 第一次出现用户确认、值得长期保留的设计时，由处理这项决定的 Agent 创建，两端随已批准的变更更新。 | 开始实现或验收前查当前约束，例如“只导出当前筛选结果”。 |
| `DECISIONS.md` | 处理决定的 Agent 在用户确认重要取舍后记录日期、理由、备选项和影响范围。 | 以后有人问“为什么这样做”时查这里。例如，为什么选择按币种精度输出金额。 |
| `.ai/explore/E001/brief.md` | 用户要求独立探索后，发起一方整理共同问题、约束、成功标准和待解问题。 | Gemini 和 Astra 在各写自己的方案前读同一份 brief，确保讨论的是同一个问题。 |
| `.ai/explore/E001/gemini.md` | Gemini 写自己的候选方案、依据、风险和验证办法。 | 用户同意交换方案后，Astra 才读取并比较。 |
| `.ai/explore/E001/astra.md` | Astra 在相同约束下独立写方案。 | 用户同意交换方案后，Gemini 才读取并比较。最后获批的结论可以写入规格或决策记录。 |
| `.ai/tasks/T001.md` | 派单方写目标、约束、Owner、Reviewer 和验收条件。Owner 实现后填写 `Result`，Reviewer 验收后填写 `Review`。 | 想知道“谁接手、做了什么、测过什么、是否通过”，直接打开这一个文件。返工也在原任务里追加结果，保留先前结论及其对应版本。 |
| `.ai/sync/to-astra.md` | Gemini 有需要告知 Astra 的决定、事实或待办时追加。 | 切到 Codex 后，Astra 读自己的收件箱，处理后清理已处理的条目。 |
| `.ai/sync/to-gemini.md` | Astra 有需要告知 Gemini 的更新时追加。 | 切到 Antigravity 后，Gemini 读取并处理。重要结论应先记入任务单、规格或决策记录，再清理消息。 |

## 仓库内容

可安装的 [Skill](skills/gemini-with-astra/SKILL.md) 包含[常驻规则模板](skills/gemini-with-astra/assets/RESIDENT.md)、[完整协作协议](skills/gemini-with-astra/assets/PROTOCOL.md)和两个 Python 脚本。仓库另附[回归测试](tests/test_skill.py)，使用临时 Git 仓库和独立测试用户目录，覆盖两种模式、规则保护、重复初始化、冲突处理和工作区指纹。

本项目采用 [MIT License](LICENSE)。
