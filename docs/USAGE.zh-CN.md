# AI Continuity 中文使用说明

AI Continuity 让 Claude Code 和 Codex CLI 在同一个项目里接着上一次对话继续工作。
例如：你先和 Claude 讨论需求，退出后改用 Codex，Codex 可以读到当前目标、已确认
决定和最近几轮上下文，不需要你重新复述。

目前验证过的环境是 macOS + zsh，并且电脑上已经安装 Claude Code 或 Codex CLI。

想先看最短流程，可以打开
[四步可视化引导](https://ai-continuity-welcome.amber-moth-2612.chatgpt.site)。
安装器在真实终端中完成后会自动打开它；以后运行 `continuity-guide` 可以再次打开。
自动化安装或不想弹出浏览器时，使用 `AI_CONTINUITY_NO_OPEN=1`。

## 最短上手流程

### 1. 安装一次

在终端运行：

```bash
curl -fsSL https://raw.githubusercontent.com/mxwlab/ai-continuity/main/install.sh | bash
```

安装完成后关闭当前终端，再打开一个新终端。AI Continuity 默认安装在：

```text
~/.local/share/ai-continuity
```

### 2. 给一个项目开启连续对话

进入你真正工作的项目目录，然后执行：

```bash
cd /path/to/your/project
continuity-onboard .
```

把 `/path/to/your/project` 换成项目的真实路径。例如：

```bash
cd ~/workspace/my-app
continuity-onboard .
```

每个项目只需要执行一次。AI Continuity 不会自动接管电脑上的其他项目。

### 3. 确认接入成功

仍然在项目目录中运行：

```bash
cat .ai-continuity/continuity.conf
```

看到类似下面的内容就表示项目已经接入：

```text
AI_CONTINUITY_CONVERSATION=my-app-live
```

### 4. 像平常一样使用

从这个项目目录或它的子目录启动 Claude 或 Codex：

```bash
claude
```

或者：

```bash
codex
```

命令不需要加任何新参数。只要当前目录属于已接入的项目，AI Continuity 就会在启动
CLI 时注入这个项目的连续对话上下文；在未接入的项目或普通目录里，`claude` 和
`codex` 仍是原来的命令。

## 第一次切换可以这样测试

1. 在已接入项目里启动 `claude`。
2. 告诉它一个明确目标，例如“我们正在实现登录页，先确定接口字段，下一步写测试”。
3. 正常结束 Claude 会话。
4. 仍在同一项目目录里启动 `codex`。
5. 直接说“继续刚才的任务”，观察它是否接上目标、决定和下一步。

反过来从 Codex 切换到 Claude 也一样。连续上下文按项目隔离，不要让两个无关项目
共用同一个 conversation id。

## 多个项目怎么用

每个需要连续对话的项目分别执行一次：

```bash
cd ~/workspace/project-a
continuity-onboard .

cd ~/workspace/project-b
continuity-onboard .
```

默认 id 根据项目目录名生成。如果两个无关项目的目录同名，请手动指定不同 id：

```bash
cd /path/to/client-a/app
continuity-onboard . client-a-app

cd /path/to/client-b/app
continuity-onboard . client-b-app
```

规则很简单：一个项目对应一个 conversation id。

## 桌面端怎么用

项目接入后会生成 `.ai-continuity/desktop-context.md`，并定时刷新。桌面端需要打开
这个项目，并遵循项目中的 AI Continuity 指令读取该文件或调用 MCP。

CLI 的启动注入是自动的；桌面端目前属于辅助模式，不能保证每个客户端都完全自动。
首次接入后建议重启一次桌面应用。

## 数据放在哪里

默认数据保存在本机：

```text
~/Library/Application Support/AI Continuity/
├── runtime/
└── logs/
```

每个人安装后都是独立的本地实例。数据不会自动同步到云端，也不会自动分享给其他
朋友或其他电脑。原始事件内容默认在 30 天后清理，必要的事件元数据会保留。

## 暂停某个项目

在项目目录运行：

```bash
continuity-offboard .
```

这会移除该项目的接入标记、生成的桌面上下文、项目指令块和刷新任务，但默认保留
已有的本地连续对话数据。

以后想重新开启，回到项目里再次运行：

```bash
continuity-onboard .
```

## 完全卸载

先对不再使用的项目执行 `continuity-offboard .`，然后运行：

```bash
~/.local/share/ai-continuity/bin/continuity-uninstall
```

普通卸载会移除 shell、MCP 和定时清理集成，但保留本地数据。如果确认连运行数据和
日志也不要了，再显式执行：

```bash
~/.local/share/ai-continuity/bin/continuity-uninstall --purge
```

## 常见问题

### 提示 `command not found: continuity-onboard`

安装后需要打开新终端。也可以在当前终端执行：

```bash
source ~/.zshrc
```

### Claude 或 Codex 没有接上上下文

先确认当前目录位于已接入项目中：

```bash
cat .ai-continuity/continuity.conf
```

然后确认对应 MCP：

```bash
claude mcp get ai-continuity
```

或：

```bash
codex mcp list
```

如果安装时出现 MCP warning，修复对应 CLI 配置后重新运行安装命令即可；安装器支持
重复执行。

### 换到另一个项目后出现了不相关上下文

检查两个项目的 `.ai-continuity/continuity.conf`，确保没有使用相同的 conversation
id。给其中一个项目执行 `continuity-offboard .`，再用新的显式 id 重新接入。

### 可以只安装 Claude 或只安装 Codex 吗？

可以。至少安装其中一个即可；只有一个 CLI 时，它仍能保存和恢复这个项目的连续
上下文。安装两个 CLI 才能体验 Claude 与 Codex 之间的切换。
