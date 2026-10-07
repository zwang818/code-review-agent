"""Deterministic offline stand-in; never presented as a real LLM."""

import json
import uuid


class DemoClient:
    """Drive real tools from their observations, then render finite AST rules.

    This makes the infrastructure demonstrable without network credentials.
    It does not implement natural-language reasoning or general bug detection.
    """

    @staticmethod
    def _calls(items):
        return {"role": "assistant", "content": None, "tool_calls": [
            {"id": "demo_" + uuid.uuid4().hex, "type": "function",
             "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}}
            for name, args in items
        ]}

    def complete(self, messages: list, tools: list, tool_choice: str = "auto") -> dict:
        start = max(i for i, message in enumerate(messages) if message["role"] == "user")
        try:
            task = json.loads(messages[start]["content"])
            if not isinstance(task, dict) or task.get("task") != "review":
                raise ValueError("not review")
        except (ValueError, TypeError):
            previous = next((m["content"] for m in reversed(messages[:start])
                             if m["role"] == "assistant" and m.get("content")), "还没有上一轮报告。")
            return {"role": "assistant", "content":
                    "离线演示不具备自由问答能力。当前会话已保留上一轮报告，下面复用其内容；"
                    "要针对追问生成新分析，请配置真实模型。\n\n" + previous[:8000]}
        definitions, observations = {}, []
        for message in messages[start + 1:]:
            for call in message.get("tool_calls", []):
                definitions[call["id"]] = (call["function"]["name"], json.loads(call["function"]["arguments"]))
            if message["role"] == "tool":
                name, args = definitions[message["tool_call_id"]]
                observations.append((name, args, json.loads(message["content"])))
        listing = next((r for name, _, r in observations if name == "list_files"), None)
        if tool_choice != "none":
            if listing is None:
                return self._calls([("list_files", {"path": task["target"]})])
            if listing["ok"]:
                for path in listing["data"]["files"][:3]:
                    pending = [(name, {"path": path}) for name in ("read_file", "analyze_python")
                               if not any(n == name and args["path"] == path for n, args, _ in observations)]
                    if pending:
                        return self._calls(pending)
        return {"role": "assistant", "content": self._report(observations, listing)}

    @staticmethod
    def _report(observations, listing) -> str:
        lines = ["# Python 代码审查报告", "",
                 "> 离线演示：使用确定性调度与有限 AST 规则，没有调用 LLM，也没有运行待审查代码。", "",
                 "## 审查范围", ""]
        for name, args, result in observations:
            if not result["ok"]:
                lines.append("- `%s` 对 `%s` 失败：%s" % (name, args["path"], result["error"]))
            elif name == "read_file":
                data = result["data"]
                if data["total_lines"] == 0:
                    lines.append("- `%s`：空文件，已读取。" % data["path"])
                    continue
                lines.append("- `%s`：读取 %d–%d 行，共 %d 行。%s" % (
                    data["path"], data["start_line"], data["end_line"], data["total_lines"],
                    "存在截断，未完整读取。" if data["truncated"] else "已完整读取。"))
        if listing and listing["ok"]:
            data = listing["data"]
            if not data["files"]:
                lines.append("- 目标中没有可审查的 Python 文件。")
            if len(data["files"]) > 3:
                lines.append("- 离线模式最多检查前三个文件，其余 %d 个未检查。" % (len(data["files"]) - 3))
            if data.get("truncated"):
                lines.append("- 文件列表已达到资源限制，未完整枚举。")
            if data.get("inaccessible_directories"):
                lines.append("- 存在无法访问的目录。")
        findings, analyzed = [], 0
        for name, _, result in observations:
            if name != "analyze_python" or not result["ok"]:
                continue
            analyzed += 1
            data = result["data"]
            lines.append("- `%s`：%s。" % (data["path"], "AST 语法解析通过" if data["syntax_ok"] else "语法解析失败"))
            if data.get("truncated"):
                lines.append("- `%s`：AST 结果已截断，仅报告返回的规则线索。" % data["path"])
            if not data["syntax_ok"]:
                error = data["syntax_error"]
                findings.append({"path": data["path"], "line": error["line"], "severity": "高",
                                 "title": "Python 语法错误", "trigger": "Python 解析该文件时。",
                                 "impact": error["message"], "suggestion": "修正语法后重新审查。"})
            findings.extend(dict(item, path=data["path"]) for item in data["findings"])
        lines += ["", "## 问题清单", ""]
        findings.sort(key=lambda f: ({"高": 0, "中": 1, "低": 2}[f["severity"]], f["path"], f["line"]))
        for index, item in enumerate(findings, 1):
            lines += ["### %d. [%s] %s" % (index, item["severity"], item["title"]), "",
                      "- 位置：`%s:%d`" % (item["path"], item["line"]),
                      "- 触发条件：" + item["trigger"], "- 影响：" + item["impact"],
                      "- 修改建议：" + item["suggestion"], ""]
        if not findings:
            lines.append("有限规则未发现问题。" if analyzed else "没有成功取得 AST 分析结果，无法给出审查结论。")
        lines += ["", "## 验证建议", "",
                  "对可变默认参数，连续调用并检查各次状态是否独立；对异常处理，主动构造失败输入。",
                  "对于动态执行，核实参数是否来自外部用户，以及同名函数是否覆盖内置函数。", "",
                  "## 限制", "",
                  "本报告没有运行测试。规则未覆盖跨文件逻辑、变量除零和业务正确性。",
                  "规则命中需要人工核实，未命中不代表没有缺陷；真实模型模式才支持按自然语言重点分析和追问。"]
        return "\n".join(lines)
