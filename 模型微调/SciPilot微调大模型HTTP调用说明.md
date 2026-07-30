# SciPilot 微调大模型 HTTP 调用说明

## 1. 接入结论

该服务兼容 OpenAI Chat Completions 协议。网页不能直接请求讯飞 MaaS；推荐链路如下：

```text
浏览器 / SciPilot 前端
        │ 只携带本系统登录凭证和对话内容
        ▼
SciPilot FastAPI 后端：POST /api/ai/chat
        │ 在服务端读取 API Key、modelId、resourceId
        ▼
讯飞星辰 MaaS：POST https://maas-api.cn-huabei-1.xf-yun.com/v2/chat/completions
```

核心配置如下：

| 项目 | 值或来源 |
| --- | --- |
| 服务名称 | `SciPilot` |
| 协议 | HTTPS |
| 请求方法 | `POST` |
| Base URL | `https://maas-api.cn-huabei-1.xf-yun.com/v2` |
| 完整接口 | `https://maas-api.cn-huabei-1.xf-yun.com/v2/chat/completions` |
| 鉴权 | `Authorization: Bearer <API_KEY>` |
| 模型 ID | 控制台“模型服务卡片”中的 `modelId` |
| 微调资源 ID | 控制台“模型服务卡片”中的 `resourceId`，通过 HTTP 请求头 `lora_id` 传递 |
| 请求格式 | `application/json` |
| 非流式响应 | `application/json` |
| 流式响应 | Server-Sent Events（SSE），通常为 `text/event-stream` |

注意：

1. 当前服务卡片显示的 Base URL 是 `/v2`，所以本文使用 HTTPS `/v2`。若控制台“调用信息”以后显示其他地址，以控制台为准。
2. 完整 Chat Completions 地址由 Base URL 加 `/chat/completions` 组成。
3. 微调服务应发送 `lora_id` 请求头，其值是模型服务卡片上的 `resourceId`，不是训练任务 ID，也不是 `modelId`。
4. `modelId` 和 `resourceId` 当前未保存在仓库中，部署前必须从服务卡片复制并放入后端环境变量。

## 2. 密钥和服务参数配置

以下变量只配置在后端运行环境、服务器密钥管理服务或本机未提交的 `backend/.env` 中：

```dotenv
SCIPILOT_LLM_BASE_URL=https://maas-api.cn-huabei-1.xf-yun.com/v2
SCIPILOT_LLM_API_KEY=<从服务卡片取得，仅放后端>
SCIPILOT_LLM_MODEL_ID=<模型服务卡片上的 modelId>
SCIPILOT_LLM_RESOURCE_ID=<模型服务卡片上的 resourceId>
```

安全要求：

- 不得把 API Key 放入 Markdown、Git、前端源码、浏览器环境变量、接口响应或日志。
- 不要使用 `VITE_`、`NEXT_PUBLIC_` 等会打包进浏览器代码的变量名前缀保存密钥。
- 浏览器只请求 SciPilot 自有后端，不直接请求 `maas-api.cn-huabei-1.xf-yun.com`。
- 本次提供的截图中已经显示过认证信息。应在平台控制台轮换相关凭据，再将新值配置到后端密钥环境中。
- 建议启动时检查四个变量是否齐全；缺少时让服务启动失败或让 AI 接口返回 `503`，不要回退到硬编码凭据。

## 3. 上游 HTTP 请求规范

### 3.1 请求行和请求头

```http
POST /v2/chat/completions HTTP/1.1
Host: maas-api.cn-huabei-1.xf-yun.com
Authorization: Bearer <SCIPILOT_LLM_API_KEY>
Content-Type: application/json
Accept: application/json
lora_id: <SCIPILOT_LLM_RESOURCE_ID>
```

流式请求建议将 `Accept` 改为：

```http
Accept: text/event-stream
```

`lora_id` 是 HTTP 请求头。不要把它误写进 JSON 请求体。使用 OpenAI Python SDK 时，对应写法是 `extra_headers={"lora_id": resource_id}`。

### 3.2 最小非流式请求体

```json
{
  "model": "<SCIPILOT_LLM_MODEL_ID>",
  "messages": [
    {
      "role": "system",
      "content": "你是 SciPilot 科研助手。"
    },
    {
      "role": "user",
      "content": "请概括这篇论文的研究方法。"
    }
  ],
  "stream": false,
  "temperature": 0.7,
  "max_tokens": 2048,
  "search_disable": true
}
```

### 3.3 主要请求参数

| 参数 | 类型 | 必填 | 建议值 | 说明 |
| --- | --- | --- | --- | --- |
| `model` | string | 是 | 后端固定为 `SCIPILOT_LLM_MODEL_ID` | 服务卡片中的 `modelId`，不要接受前端任意覆盖 |
| `messages` | array | 是 | 见下文 | 对话历史，按发生顺序传递 |
| `stream` | boolean | 否 | 网页聊天建议 `true` | 默认 `false`；`true` 时返回 SSE 增量数据 |
| `temperature` | number | 否 | `0.2`～`0.7` | 通常范围 `[0,1]`、默认 `0.7`；不同底座可能有差异 |
| `max_tokens` | integer | 否 | 从 `2048` 起调 | 默认 `2048`；输入 token 与输出上限之和必须小于模型上下文长度 |
| `search_disable` | boolean | 否 | `true` | 默认 `true`，表示关闭联网搜索 |
| `show_ref_label` | boolean | 否 | `false` | 联网搜索时设为 `true` 才返回信源信息 |
| `stream_options` | object | 否 | `{"include_usage": true}` | 流式模式中返回 token 用量 |
| `enable_thinking` | boolean | 否 | 按底座能力决定 | 开启深度思考；仅对支持该能力的模型有效 |
| `reasoning_effort` | string | 否 | 按底座能力决定 | 部分模型支持 `low`、`medium`、`high`，新模型的取值可能不同 |
| `response_format` | object | 否 | 谨慎启用 | `{"type":"json_object"}`；只对支持 JSON Mode 的底座有效 |
| `stop` | string[] | 否 | 通常不传 | 仅部分 DeepSeek 模型支持，最多 4 个停止字符串 |
| `continue_final_message` | boolean | 否 | 通常不传 | 仅部分 DeepSeek 模型支持对最后一条 assistant 消息续写 |
| `tools` | array | 否 | 按底座能力决定 | Function Calling 工具定义，并非所有模型支持 |
| `tool_choice` | string | 否 | `auto` | 可为 `auto`、`none`、`required` |

`lora_id` 不在本表中，因为它属于 HTTP 请求头，而不是 JSON 参数。对于本微调模型，后端应固定发送该请求头。

### 3.4 `messages` 规则

每条消息至少包含 `role` 和 `content`：

| `role` | 用途 |
| --- | --- |
| `system` | 后端设置角色、边界和任务说明。建议由后端注入，不允许普通网页用户直接覆盖 |
| `user` | 用户输入 |
| `assistant` | 历史模型回复 |
| `tool` | 工具执行结果；仅用于 Function Calling 流程 |

多轮对话示例：

```json
[
  {"role": "system", "content": "你是 SciPilot 科研助手。"},
  {"role": "user", "content": "什么是消融实验？"},
  {"role": "assistant", "content": "消融实验用于分析不同模块对模型效果的贡献。"},
  {"role": "user", "content": "请给出一个设计模板。"}
]
```

普通对话的最后一条消息应是当前 `user` 问题。网页端或后端需要保存历史消息，但发送前应按模型上下文上限裁剪，不能无限追加。

## 4. 原生 HTTP 调用示例

以下命令只读取 PowerShell 环境变量，不包含真实密钥。

### 4.1 非流式调用

```powershell
$body = @{
    model = $env:SCIPILOT_LLM_MODEL_ID
    messages = @(
        @{ role = "system"; content = "你是 SciPilot 科研助手。" }
        @{ role = "user"; content = "请用三点概括迁移学习。" }
    )
    stream = $false
    temperature = 0.7
    max_tokens = 2048
    search_disable = $true
} | ConvertTo-Json -Depth 10

curl.exe --request POST `
  "$env:SCIPILOT_LLM_BASE_URL/chat/completions" `
  --header "Authorization: Bearer $env:SCIPILOT_LLM_API_KEY" `
  --header "Content-Type: application/json" `
  --header "Accept: application/json" `
  --header "lora_id: $env:SCIPILOT_LLM_RESOURCE_ID" `
  --data-raw $body
```

### 4.2 流式调用

```powershell
$body = @{
    model = $env:SCIPILOT_LLM_MODEL_ID
    messages = @(
        @{ role = "user"; content = "请介绍你的科研辅助能力。" }
    )
    stream = $true
    stream_options = @{ include_usage = $true }
    temperature = 0.7
    max_tokens = 2048
    search_disable = $true
} | ConvertTo-Json -Depth 10

curl.exe --no-buffer --request POST `
  "$env:SCIPILOT_LLM_BASE_URL/chat/completions" `
  --header "Authorization: Bearer $env:SCIPILOT_LLM_API_KEY" `
  --header "Content-Type: application/json" `
  --header "Accept: text/event-stream" `
  --header "lora_id: $env:SCIPILOT_LLM_RESOURCE_ID" `
  --data-raw $body
```

## 5. 响应格式

### 5.1 非流式成功响应

实际字段会随底座模型能力变化，业务代码至少应安全读取 `choices[0].message.content`：

```json
{
  "id": "<request-id>",
  "object": "chat.completion",
  "created": 1760000000,
  "model": "<actual-model>",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "模型回复内容"
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 100,
    "completion_tokens": 80,
    "total_tokens": 180
  }
}
```

建议读取方式：

```javascript
const content = data?.choices?.[0]?.message?.content ?? "";
const finishReason = data?.choices?.[0]?.finish_reason;
const usage = data?.usage;
```

常见 `finish_reason`：

| 值 | 含义 | 页面处理 |
| --- | --- | --- |
| `stop` | 正常完成 | 正常展示 |
| `length` | 达到输出长度上限 | 提示用户“回答可能未完成”，可提供“继续”按钮 |
| `tool_calls` | 模型请求调用工具 | 后端执行允许的工具，不能由浏览器任意执行 |

### 5.2 流式 SSE 响应

`stream=true` 时，上游逐条返回 `data:` 事件。典型结构如下：

```text
data: {"choices":[{"index":0,"delta":{"role":"assistant","content":"迁移"},"finish_reason":null}]}

data: {"choices":[{"index":0,"delta":{"content":"学习"},"finish_reason":null}]}

data: {"choices":[{"index":0,"delta":{},"finish_reason":"stop"}],"usage":{"total_tokens":180}}

data: [DONE]
```

处理规则：

1. 按 SSE 空行分隔事件，不要假设一次网络读取正好是一条 JSON。
2. 只解析以 `data:` 开头的行。
3. 收到 `[DONE]` 后结束读取。
4. 把 `choices[0].delta.content` 追加到当前 assistant 消息。
5. `delta.content`、`choices` 或 `usage` 可能缺失，必须使用空值保护。
6. 代理层必须关闭响应缓冲，否则网页会等到全部完成后才看到文字。

### 5.3 错误响应

错误体通常兼容以下结构：

```json
{
  "error": {
    "message": "错误说明及 request id",
    "type": "one_api_error"
  }
}
```

| HTTP 状态 | 常见原因 | 后端处理 |
| --- | --- | --- |
| `400` | JSON、参数、消息格式或模型能力不匹配 | 不重试；记录必要的字段名，向前端返回可理解提示 |
| `401` | API Key 无效 | 不重试；检查后端密钥配置 |
| `403` | Key 无模型权限、`modelId` 或 `resourceId` 不匹配 | 不重试；核对服务卡片 |
| `429` | 请求过快或额度耗尽 | 区分限流与配额；限流可指数退避，配额问题需告警 |
| `500` | 上游内部错误 | 有限重试并记录 request id |
| `503` | 引擎过载 | 有限重试并提示稍后再试 |

只可在尚未输出任何 SSE 文本时自动重试流式请求；已经输出部分内容后重试会导致重复文本。建议对 `429`、`500`、`503` 使用带随机抖动的指数退避，例如最多重试 2 次，等待约 1 秒、2 秒。

## 6. SciPilot FastAPI 后端参考实现

项目后端已经使用 FastAPI。下面示例把模型配置固定在服务器端，对浏览器只暴露 SciPilot 自有接口。依赖为 `httpx`。

```python
import json
import os
from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

router = APIRouter()

BASE_URL = os.getenv(
    "SCIPILOT_LLM_BASE_URL",
    "https://maas-api.cn-huabei-1.xf-yun.com/v2",
).rstrip("/")


class Message(BaseModel):
    # system 角色由后端统一注入，普通浏览器用户只能提交对话内容。
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=50_000)


class ChatRequest(BaseModel):
    messages: list[Message] = Field(min_length=1, max_length=100)
    stream: bool = True
    temperature: float = Field(default=0.7, ge=0, le=1)
    max_tokens: int = Field(default=2048, ge=1, le=8192)


def require_setting(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise HTTPException(status_code=503, detail=f"服务器缺少 {name} 配置")
    return value


def upstream_headers(stream: bool) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {require_setting('SCIPILOT_LLM_API_KEY')}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream" if stream else "application/json",
        "lora_id": require_setting("SCIPILOT_LLM_RESOURCE_ID"),
    }


def upstream_payload(body: ChatRequest) -> dict:
    return {
        "model": require_setting("SCIPILOT_LLM_MODEL_ID"),
        "messages": [
            {"role": "system", "content": "你是 SciPilot 科研助手。"},
            *[message.model_dump() for message in body.messages],
        ],
        "stream": body.stream,
        "temperature": body.temperature,
        "max_tokens": body.max_tokens,
        "search_disable": True,
        **(
            {"stream_options": {"include_usage": True}}
            if body.stream
            else {}
        ),
    }


def safe_upstream_error(response: httpx.Response) -> dict:
    try:
        error = response.json().get("error", {})
    except (ValueError, AttributeError):
        error = {}
    return {
        "message": error.get("message", "大模型服务调用失败"),
        "type": error.get("type", "upstream_error"),
    }


@router.post("/api/ai/chat")
async def chat(body: ChatRequest):
    url = f"{BASE_URL}/chat/completions"
    headers = upstream_headers(body.stream)
    payload = upstream_payload(body)
    timeout = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0)

    if not body.stream:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, headers=headers, json=payload)
        if response.is_error:
            raise HTTPException(
                status_code=response.status_code,
                detail=safe_upstream_error(response),
            )
        return response.json()

    # 流式模式需要保持 httpx client 存活到 SSE 转发结束。
    client = httpx.AsyncClient(timeout=timeout)
    request = client.build_request("POST", url, headers=headers, json=payload)
    response = await client.send(request, stream=True)

    if response.is_error:
        await response.aread()
        detail = safe_upstream_error(response)
        await response.aclose()
        await client.aclose()
        raise HTTPException(status_code=response.status_code, detail=detail)

    async def relay():
        try:
            async for chunk in response.aiter_raw():
                yield chunk
        finally:
            await response.aclose()
            await client.aclose()

    return StreamingResponse(
        relay(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )
```

将 `router` 注册到现有 FastAPI 应用即可。正式实现还应接入项目已有的登录鉴权、限流、审计和异常日志，而不是公开匿名代理。

若项目仍使用 Pydantic v1，把 `message.model_dump()` 改为 `message.dict()`。

## 7. 网页端调用自有后端

### 7.1 非流式

```javascript
async function sendChat(messages) {
  const response = await fetch("/api/ai/chat", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages, stream: false }),
  });

  const data = await response.json();
  if (!response.ok) {
    throw new Error(data?.detail?.message ?? "大模型请求失败");
  }

  return data?.choices?.[0]?.message?.content ?? "";
}
```

### 7.2 流式

```javascript
async function streamChat(messages, onText, signal) {
  const response = await fetch("/api/ai/chat", {
    method: "POST",
    credentials: "include",
    signal,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages, stream: true }),
  });

  if (!response.ok) {
    const data = await response.json().catch(() => null);
    throw new Error(data?.detail?.message ?? "大模型请求失败");
  }
  if (!response.body) throw new Error("浏览器不支持流式响应");

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });

    const events = buffer.split(/\r?\n\r?\n/);
    buffer = events.pop() ?? "";

    for (const event of events) {
      const data = event
        .split(/\r?\n/)
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).trimStart())
        .join("\n");

      if (!data) continue;
      if (data === "[DONE]") return;

      const chunk = JSON.parse(data);
      const text = chunk?.choices?.[0]?.delta?.content ?? "";
      if (text) onText(text);
    }

    if (done) break;
  }
}

// 页面停止按钮可调用 controller.abort()。
const controller = new AbortController();
streamChat(
  [{ role: "user", content: "请解释注意力机制。" }],
  (text) => console.log(text),
  controller.signal,
);
```

前端发送的 `messages` 不应包含 API Key、`modelId`、`resourceId` 或可覆盖后端 system prompt 的字段。

## 8. 上线前检查清单

- [ ] 已在讯飞控制台轮换截图中暴露过的认证信息。
- [ ] `SCIPILOT_LLM_API_KEY` 只存在于后端密钥环境，未进入 Git 和前端产物。
- [ ] 已从同一张服务卡片取得匹配的 `modelId` 与 `resourceId`。
- [ ] 使用 `POST /v2/chat/completions`，并通过请求头发送 `lora_id`。
- [ ] 自有 `/api/ai/chat` 接口要求用户登录，并设置单用户和全局限流。
- [ ] 后端限制消息数量、单条长度、总请求体大小和 `max_tokens`。
- [ ] SSE 代理已关闭 Nginx 等中间层缓冲，并可在浏览器中逐字显示。
- [ ] 用户取消请求时，浏览器会中断请求，后端会关闭上游连接。
- [ ] 日志不记录 Authorization 请求头、完整 Prompt、敏感文件内容或完整模型响应。
- [ ] 记录上游 HTTP 状态、耗时、token 用量及错误中的 request id，便于排障。
- [ ] 对 `401`、`403` 不自动重试；对 `429`、`500`、`503` 仅有限退避重试。
- [ ] 已分别验证中文输入、长文本、多轮对话、超时、取消、限流和上游异常。

## 9. 联调顺序

1. 在开发机后端环境中配置四个 `SCIPILOT_LLM_*` 变量。
2. 先运行第 4.1 节非流式命令，确认 `modelId`、API Key 和 `resourceId` 匹配。
3. 再运行第 4.2 节，确认终端能持续收到 SSE 数据。
4. 接入 FastAPI 路由，仅用后端请求上游。
5. 最后连接网页端，检查浏览器网络请求中不存在任何讯飞密钥或 `lora_id`。

## 10. 参考资料

- [讯飞开放平台：推理服务 HTTP 协议](https://www.xfyun.cn/doc/spark/%E6%8E%A8%E7%90%86%E6%9C%8D%E5%8A%A1-http.html)
- 服务管控 → 模型服务列表 → SciPilot 服务卡片 → 调用信息（以控制台实时信息为准）

