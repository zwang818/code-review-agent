"""Command-line entry point and a small interactive session."""

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .agent import ReviewAgent
from .config import Settings, load_dotenv
from .demo import DemoClient
from .errors import AgentError
from .llm import ChatClient
from .tools import ToolRegistry


def review_task(target: str, focus: str) -> str:
    return json.dumps({"task": "review", "target": target, "focus": focus}, ensure_ascii=False)


def write_report(path: str, report: str) -> None:
    destination = Path(path).expanduser()
    if destination.exists():
        raise AgentError("报告路径已存在；请换一个文件名，避免覆盖已有文件。")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8") as stream:
        stream.write(report + "\n")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Python 代码审查 Agent：只读工具 + LLM + 会话记忆")
    parser.add_argument("target", nargs="?", help="待审查 .py 文件或目录，相对 --root")
    parser.add_argument("--root", default=".", help="允许审查的根目录，默认当前目录")
    parser.add_argument("--focus", default="检查潜在 Bug、边界条件和异常处理。", help="审查重点")
    parser.add_argument("--chat", action="store_true", help="审查后进入交互会话；也可单独使用")
    parser.add_argument("--demo", action="store_true", help="离线规则演示；不会调用真实 LLM")
    parser.add_argument("--report", help="将首次报告保存为 Markdown（不覆盖已有文件）")
    parser.add_argument("--env-file", default=".env", help="配置文件，默认当前目录的 .env")
    parser.add_argument("--quiet", action="store_true", help="隐藏步骤日志，stdout 仅输出报告")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)
    if args.target is None and not args.chat:
        if args.report:
            parser.error("--report 需要同时提供审查目标")
        parser.print_help()
        return 0
    if args.report and not args.target:
        parser.error("--report 需要同时提供审查目标")

    def event(message):
        if not args.quiet:
            print(message, file=sys.stderr, flush=True)

    try:
        load_dotenv(Path(args.env_file).expanduser())
        settings = Settings.from_env(require_api=not args.demo)
        tools = ToolRegistry(Path(args.root).expanduser())
        root = tools.root
        client = DemoClient() if args.demo else ChatClient(settings, on_retry=event)
        agent = ReviewAgent(client, tools, settings, on_event=event)
        mode = "离线规则演示（未调用 LLM）" if args.demo else "真实模型：" + settings.model
        event("[启动] %s；审查根目录：%s" % (mode, root))
        last_report = ""
        if args.target:
            # Fail early on invalid user-selected targets instead of spending an API call.
            target = tools.resolve(args.target).relative_to(root).as_posix()
            result = agent.run(review_task(target, args.focus))
            last_report = result.report
            print(last_report)
            event("[完成] 决策 %d 轮，实际工具调用 %d 次。" % (result.model_calls, result.tool_calls))
            if args.report:
                write_report(args.report, last_report)
                event("[报告] 已保存到 " + str(Path(args.report).resolve()))
        if not args.chat:
            return 0
        print("\n交互命令：/review 路径、/save 路径、/reset、/help、/exit。其他输入作为追问。")
        while True:
            try:
                text = input("\n你> ").strip()
            except EOFError:
                break
            if not text:
                continue
            if text in ("/exit", "/quit"):
                break
            if text == "/help":
                print("/review examples/buggy_order.py  审查文件（路径可包含空格，无需引号）\n"
                      "/save reports/review.md       保存最近报告，不覆盖已有文件\n"
                      "/reset                        清空当前会话\n"
                      "/exit                         退出\n其他文字：针对上下文追问。")
                continue
            if text == "/reset":
                agent.reset()
                last_report = ""
                print("已清空会话记忆和最近报告。")
                continue
            try:
                if text.startswith("/save "):
                    if not last_report:
                        raise AgentError("还没有可保存的报告。")
                    write_report(text[6:].strip(), last_report)
                    print("报告已保存。")
                    continue
                if text.startswith("/review "):
                    target = tools.resolve(text[8:].strip()).relative_to(root).as_posix()
                    task = review_task(target, args.focus)
                elif text.startswith("/"):
                    raise AgentError("未知命令，请输入 /help 查看用法。")
                else:
                    task = text
                result = agent.run(task)
                last_report = result.report
                print("\n助手>\n" + last_report)
            except (AgentError, OSError) as exc:
                print("错误：%s" % exc, file=sys.stderr)
        return 0
    except (AgentError, OSError) as exc:
        print("错误：%s" % exc, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n已取消。", file=sys.stderr)
        return 130
