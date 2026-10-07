# Python 代码审查 Agent

软件工程 Homework 1 项目。用户输入 Python 文件或项目目录，Agent 调用只读工具获取源码与 AST 信息，再输出包含问题位置、触发条件、影响和修改建议的中文报告。

真实模式采用 **LLM 决策 → 工具调用 → 观察工具结果 → 继续分析或输出报告** 的循环。支持命令行交互、会话记忆、有限重试和 Markdown 报告导出。运行和测试仅依赖 Python 标准库。

## 1. 快速运行

环境要求：Python **3.9 或更高版本**。在 macOS/Linux 使用 `python3`，Windows 可使用 `python` 或 `py -3`。

```bash
cd /Users/mac/SoftProjects/week1/code-review-agent
python3 -m code_review_agent --demo examples/buggy_order.py
```

这条命令不需要安装依赖、不需要 API 密钥，也不会联网。控制台可以看到文件列表、源码读取和 AST 分析的调用步骤，随后输出报告。

**`--demo` 是离线规则演示，不会调用 LLM。** 它用确定性调度器检查有限 AST 规则，用于验证程序流程，不具备一般自然语言推理能力。完成真实 Agent 功能演示时，请按下一节配置模型并去掉 `--demo`。

对照查看修正版：

```bash
python3 -m code_review_agent --demo examples/clean_order.py
```

预期反例报告包含：可变默认参数、裸 `except`、静默忽略异常和字面量除零。修正版应显示“有限规则未发现问题”。反例中的空列表平均值问题涉及变量除零，离线规则不会发现，可作为真实模型审查的验证点。

## 2. 配置真实模型

接口要求：服务和模型需要支持 **OpenAI 兼容 Chat Completions 的 `tools`、`tool_calls`、`tool_choice` 和 `tool` 消息格式**。仅支持文本聊天的接口不能完成本项目的真实工具循环。

```bash
cp .env.example .env
```

打开 `.env`，填写自己的配置：

```dotenv
OPENAI_API_KEY=填写你的密钥
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=填写账号可用且支持工具调用的模型ID
```

如使用其他兼容服务，按该服务官方文档替换 API 前缀及模型 ID。程序会在前缀后追加 `/chat/completions`，不要把完整接口路径或聊天网页地址填入 `OPENAI_BASE_URL`。不同服务对工具调用的兼容程度不同，项目不保证所有模型都可用；需要额外专有参数的服务应扩展 `llm.py`。

随后运行：

```bash
python3 -m code_review_agent examples/buggy_order.py \
  --focus "检查边界条件、默认参数共享状态和异常处理"
```

运行时，工具读到的源码会发送到配置的模型服务。Agent 自身只做静态分析，不执行、导入或修改目标代码。请使用允许发送给该服务的代码；真实调用可能产生服务商费用。

配置文件默认为**当前工作目录的 `.env`**；进程环境变量优先于文件值。使用其他配置位置时：

```bash
python3 -m code_review_agent examples/buggy_order.py --env-file /path/to/private.env
```

`.env` 支持 `KEY=VALUE`、成对单/双引号、整行注释及可选 `export` 前缀，不展开变量、不执行 shell 表达式。不要写行尾注释。

## 3. 使用方式

### 审查目录

```bash
python3 -m code_review_agent examples --focus "优先检查可能导致运行失败的缺陷"
```

真实模型先列出文件，再决定检查顺序和是否补充读取。离线演示最多检查排序后的前三个文件，并说明未检查的范围。

### 审查另一个项目

```bash
python3 -m code_review_agent --root /path/to/your/project src/order.py
```

`target` 相对于 `--root` 解释；默认根目录是当前目录。根目录内的绝对路径也支持。根目录外路径、越界符号链接、隐藏文件和依赖目录会被拒绝。

如果没有安装包，应从本项目目录运行上面的命令。也可在已有 pip/setuptools 的环境中执行 `python3 -m pip install -e .`，再从其他目录调用 `code-review-agent`；构建工具缺失时安装命令可能需要联网，直接使用 `python3 -m` 不需要安装。

### 多轮交互

```bash
python3 -m code_review_agent examples/buggy_order.py --chat
```

也可使用 `python3 -m code_review_agent --chat` 启动空会话。

```text
你> 第二个问题在什么情况下触发？给出修改示例。
你> /review examples/clean_order.py
你> /save reports/review.md
你> /reset
你> /exit
```

| 命令 | 作用 |
|---|---|
| 普通文本 | 交给模型，结合当前会话回答追问 |
| `/review 路径` | 审查新文件或目录，路径可包含空格，无需额外引号 |
| `/save 路径` | 保存最近报告，不覆盖已有文件 |
| `/reset` | 清空会话记忆和最近报告 |
| `/help` | 显示帮助 |
| `/exit`、`/quit` | 退出 |

记忆只保存在当前进程内，退出后不保留。默认最多保留4轮完整会话，超限时删除最早整轮，确保工具调用和工具结果保持配对。离线模式会保留上下文，但面对自由追问只复用上轮报告并说明能力限制。

### 保存报告

```bash
python3 -m code_review_agent --demo examples/buggy_order.py --report reports/review.md
```

`--report` 保存首次报告；交互中的后续报告可使用 `/save` 另存。两种保存方式均不覆盖已有文件。默认步骤日志输出到 stderr，报告输出到 stdout；`--quiet` 可隐藏步骤日志：

```bash
python3 -m code_review_agent --demo examples/buggy_order.py --quiet
```

退出码：`0` 表示请求流程正常完成，`1` 表示配置或运行失败，`2` 表示命令行参数错误，`130` 表示用户取消。正常完成的报告也可能说明文件未读取或存在遗漏，退出码不代表“代码审查通过”。

## 4. 功能与作业要求对应

| 作业要求 | 本项目实现 |
|---|---|
| 代码助手方向 | Python 代码审查 Agent |
| 输入、推理、工具调用、输出 | `ReviewAgent.run()` 实现多轮模型与工具循环 |
| 至少一种工具 | `list_files`、`read_file`、`analyze_python` 三个工具 |
| 命令行或简单 Web 界面 | 单次命令与 `--chat` 交互命令行 |
| LLM 调用与 Prompt 设计 | `llm.py` 与独立的 `prompts.py` |
| 上下文记忆（推荐） | 有轮数及字符预算的进程内会话记忆 |
| 错误处理与重试（推荐） | 工具错误反馈、模型失败回滚、网络与临时 HTTP 错误有限重试 |
| 源代码与文档 | 完整源码、自动化测试、README、设计文档和演示说明 |

技术栈：Python 3.9+、`urllib`、`ast`、`argparse`、`unittest`。直接实现 Agent 循环，不依赖 Agent 框架，便于阅读和解释架构。作业允许调用 LLM 原生 API，因此框架不是运行前提。

## 5. 项目结构

```text
code-review-agent/
├── code_review_agent/
│   ├── __main__.py       # python -m 入口
│   ├── cli.py            # 单次审查、交互、报告导出
│   ├── agent.py          # Agent 循环、预算与会话记忆
│   ├── llm.py            # HTTP 调用、协议校验与重试
│   ├── tools.py          # 只读文件工具、AST 与路径限制
│   ├── prompts.py        # 审查规则与输出要求
│   ├── demo.py           # 明确标注的离线规则演示
│   ├── config.py         # 环境配置与校验
│   └── errors.py         # 预期错误类型
├── examples/             # 有缺陷反例与修正版
├── tests/                # 工具、循环、CLI、HTTP 与配置测试
├── scripts/package_submission.py
├── .env.example
├── README.md
├── Design.md             # 完整设计说明
├── Desgin.md             # 与作业原文拼写对应的说明入口
├── TESTING.md            # 测试范围与结果边界
├── DEMO.md               # 一分钟演示建议
├── pyproject.toml
└── requirements.txt      # 说明无第三方运行依赖
```

详细设计见 [Design.md](Design.md)，验证说明见 [TESTING.md](TESTING.md)。

## 6. 运行测试

```bash
python3 -m unittest discover -s tests -v
```

测试不需要 API 密钥、不访问外部模型服务。传输集成测试会启动本机临时 HTTP 服务，校验实际 HTTP 请求、工具结果回传和重试。测试通过只能说明本地实现通过这些用例，不能证明外部模型可用或审查结论准确。

## 7. 配置项与资源边界

| 配置项 | 默认值 | 含义 |
|---|---:|---|
| `AGENT_TIMEOUT` | 30 | 单次 HTTP 超时秒数，0到300之间 |
| `AGENT_MAX_RETRIES` | 2 | 首次请求之外最多重试次数，允许0到5 |
| `AGENT_MAX_ROUNDS` | 10 | 允许工具决策的模型轮数，允许1到30 |
| `AGENT_MAX_TOOL_CALLS` | 24 | 单个用户任务的实际工具调用上限，允许1到100 |
| `AGENT_MEMORY_TURNS` | 4 | 保留的完整用户轮数，允许1到20 |
| `AGENT_MAX_CONTEXT_CHARS` | 100000 | 消息序列化后的字符预算，允许4000到500000 |

达到模型轮数或工具次数上限时，额外发出一次禁止工具的模型请求，基于已有证据收束报告。因此模型请求最多为 `AGENT_MAX_ROUNDS + 1` 次；每次模型请求还可能按配置发生 HTTP 重试。当前单轮任务自身超过字符预算时会报错并回滚，不会声称完成全量审查。字符预算不是精确 token 计数，模型上下文较小时应继续降低范围或预算。

工具限制：仅 `.py` 文件、单文件最多128 KiB、单次读取最多300行和约16000字符、单行最多显示2000字符。文件列表最多100个文件并限制扫描条目；AST 结构与线索各最多100项。截断和无法访问会在工具结果中明确标记。长行被截断的部分无法通过当前读取工具完整取回，应先拆分文件或人工查看。

默认排除隐藏目录、虚拟环境、依赖、构建产物及 `reports`。不提供 shell、代码执行和写文件工具。报告导出由明确的 CLI 命令完成，不由模型控制。

## 8. 常见问题

- **提示缺少密钥或模型**：填写 `.env`；只想先查看流程可使用 `--demo`。
- **HTTP 400**：检查模型是否支持工具调用，以及 `BASE_URL` 是否正确。
- **HTTP 401/403**：检查密钥、账号权限或服务访问限制。这类错误不自动重试。
- **HTTP 404**：检查 API 前缀和模型 ID。
- **HTTP 429/5xx、网络超时**：程序有限重试；额度问题仍需在服务商处处理。传输超时后重试可能发生重复计费。
- **证书错误**：检查系统证书和网络代理，项目不会关闭 TLS 校验。
- **路径被拒绝**：使用合适的 `--root`，检查目标是否为隐藏文件、排除目录或越界符号链接。
- **报告不完整或预算耗尽**：先审查一个文件，或缩小目录；未读取的部分不能当作已审查。
- **未发现问题**：只是当前分析未找到可靠线索，不代表业务逻辑正确。模型结论需要人工核实。

## 9. 作业提交

打包源代码、文档、测试和示例：

```bash
python3 scripts/package_submission.py --name "你的学号姓名"
```

默认输出到项目上一级目录，即 `week1/你的学号姓名.zip`。脚本排除 `.env`、虚拟环境、缓存、Git 元数据与运行报告，保留 `.env.example`。已有同名压缩包不会被覆盖。

提交前填写真实作者信息，完成一次真实模型联调；若录制可选视频，参考 [DEMO.md](DEMO.md)，视频不超过1分钟。按老师要求提交源代码及文档，并将“学号姓名”压缩包备份提交到 `001Homework1`，压缩包小于200MB。截止时间为 **2026年10月7日24点**。

项目没有预设学号姓名，也没有替你创建远程仓库或上传作业。需要 GitHub/Gitee 仓库时，可将此目录的源码提交到自己的仓库，并核对没有包含密钥。

## 10. 接口参考

工具调用消息格式依据 [OpenAI Function calling](https://developers.openai.com/api/docs/guides/function-calling) 和 [Chat Completions API](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)。本项目采用其中的 Chat Completions 函数工具协议；外部服务的可用模型和额外参数以各服务官方文档为准。
