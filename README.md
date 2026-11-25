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

**以下文件在实际工作中按需创建。** 刚初始化时，任务目录和设计规格通常还不存在。

| 首次发生什么 | 典型路径 | 可以在里面找到什么 |
| --- | --- | --- |
| 确认值得长期保存的设计或决定 | `SPEC.md`、`DECISIONS.md`。在 `local` 模式下位于 `.ai/docs/`，在 `private` 模式下位于 `docs/` | 已确认的需求、约束、决定及其理由 |
| 正式派单或明确要求跟踪任务 | `.ai/tasks/T001.md` | Owner、Reviewer、验收条件，以及后续的 Result 和 Review |
| 需要给另一端留下重要更新 | `.ai/sync/to-astra.md` 或 `.ai/sync/to-gemini.md` | 给接收方的变更、影响和待办 |
| 要求双方独立探索方案 | `.ai/explore/E001/` | 共同的 `brief.md` 及各自的 `gemini.md`、`astra.md` |

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

## 仓库内容

可安装的 [Skill](skills/gemini-with-astra/SKILL.md) 包含[常驻规则模板](skills/gemini-with-astra/assets/RESIDENT.md)、[完整协作协议](skills/gemini-with-astra/assets/PROTOCOL.md)和两个 Python 脚本。仓库另附[回归测试](tests/test_skill.py)，使用临时 Git 仓库和独立测试用户目录，覆盖两种模式、规则保护、重复初始化、冲突处理和工作区指纹。

本项目采用 [MIT License](LICENSE)。
