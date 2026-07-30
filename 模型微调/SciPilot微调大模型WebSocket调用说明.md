# SciPilot 微调大模型 WebSocket 调用说明

> 面向 SciPilot 网页与后端开发人员。本文不保存任何真实 APPID、APIKey 或 APISecret。  
> 文档依据：讯飞星辰 MaaS「推理服务 WebSocket 协议」「WebSocket 协议通用鉴权 URL 生成说明」及当前 SciPilot 服务卡片。  
> 更新日期：2026-07-30

## 1. 接入结论

讯飞星辰 MaaS WebSocket 接口是流式接口。推荐的网页接入链路为：

```text
SciPilot 浏览器
    │ 连接本站 WebSocket，只发送登录凭证和对话内容
    ▼
SciPilot FastAPI 后端：/ws/ai/chat
    │ 生成短期有效的签名 URL
    │ 注入 APPID、modelId、resourceId
    ▼
讯飞星辰 MaaS：wss://maas-api.cn-huabei-1.xf-yun.com/v1.1/chat
```

| 项目 | 值或来源 |
| --- | --- |
| 服务名称 | `SciPilot` |
| 协议 | WebSocket over TLS（WSS） |
| 默认上游地址 | `wss://maas-api.cn-huabei-1.xf-yun.com/v1.1/chat` |
| 握手鉴权 | HMAC-SHA256 签名 URL |
| 握手签名请求行 | `GET /v1.1/chat HTTP/1.1` |
| 应用标识 | 服务调用信息中的 `APPID` |
| 签名凭据 | 服务调用信息中的 `APIKey` 和 `APISecret` |
| 模型 ID | 模型服务卡片中的 `modelId`，写入 `parameter.chat.domain` |
| 微调资源 ID | 模型服务卡片中的 `resourceId`，作为数组元素写入 `header.patch_id` |
| 请求消息 | 建立连接后发送一个 JSON 文本帧 |
| 响应消息 | 多个 JSON 文本帧，按顺序拼接增量内容 |

必须注意：

1. WebSocket 与上一份 HTTP 调用文档的鉴权方式不同。WebSocket 使用 `APPID + APIKey + APISecret` 生成签名 URL，不能直接照搬 HTTP 的 Bearer API Key。
2. 浏览器不应直接连接讯飞上游。签名 URL 虽然短期有效，但仍属于敏感认证信息，不能返回给网页、写入日志或通过前端生成。
3. 微调模型必须传 `header.patch_id: [resourceId]`；这里是数组，不是字符串。
4. `parameter.chat.domain` 填 `modelId`，不要填 `resourceId`。
5. 部分模型的地址可能不同。若服务卡片显示的 WebSocket 地址与本文不同，以服务卡片为准，并同步修改签名使用的 host 和 path。

## 2. 后端环境变量

凭据只配置在服务器密钥环境、本机未提交的 `backend/.env` 或密钥管理服务中：

```dotenv
SCIPILOT_WS_URL=wss://maas-api.cn-huabei-1.xf-yun.com/v1.1/chat
SCIPILOT_WS_APP_ID=<服务调用信息中的 APPID>
SCIPILOT_WS_API_KEY=<仅放后端>
SCIPILOT_WS_API_SECRET=<仅放后端>
SCIPILOT_WS_MODEL_ID=<模型服务卡片中的 modelId>
SCIPILOT_WS_RESOURCE_ID=<模型服务卡片中的 resourceId>
```

安全要求：

- 不得把 APPID、APIKey、APISecret、签名 URL 写入 Markdown、Git、前端源码、接口响应或日志。
- 不得使用 `VITE_`、`NEXT_PUBLIC_` 等会进入浏览器构建产物的变量保存凭据。
- 每次建立上游连接前动态生成签名 URL，不缓存或重复使用旧签名 URL。
- 日志如需记录上游地址，只记录 `wss://.../v1.1/chat`，必须删除查询字符串。
- 截图中已显示过服务认证信息，应先在控制台轮换相关凭据，再配置新值。
- WebSocket 的 APIKey 与 APISecret 应取自同一服务调用卡片，不能混用不同应用或服务的凭据。

## 3. 签名 URL 生成

### 3.1 签名参数

握手 URL 包含三个查询参数：

| 参数 | 说明 |
| --- | --- |
| `host` | 上游 URL 的主机名：`maas-api.cn-huabei-1.xf-yun.com` |
| `date` | 当前 GMT 时间，RFC1123 格式；客户端与服务端时间误差不得超过 300 秒 |
| `authorization` | APIKey、算法、签名头和 HMAC 签名组成的字符串再次 Base64 编码后的值 |

### 3.2 签名步骤

对当前默认地址，签名原文必须严格为：

```text
host: maas-api.cn-huabei-1.xf-yun.com
date: <RFC1123 GMT 时间>
GET /v1.1/chat HTTP/1.1
```

生成过程：

1. 使用 APISecret 对上述 UTF-8 字符串执行 HMAC-SHA256。
2. 对 HMAC 二进制结果做 Base64，得到 `signature`。
3. 拼接以下 `authorization_origin`：

```text
api_key="<APIKey>", algorithm="hmac-sha256", headers="host date request-line", signature="<signature>"
```

4. 对 `authorization_origin` 整体做 Base64，得到 `authorization`。
5. 对 `authorization`、`date`、`host` 使用标准 URL 编码并附加到 WSS 地址。

容易出错的地方：

- WebSocket 握手签名使用 `GET`，不是 HTTP Chat Completions 接口使用的 `POST`。
- 三行签名原文之间只有一个 `\n`，末尾不要额外加换行。
- `host` 不包含 `wss://`，也不包含 path。
- `date` 使用 GMT/RFC1123，例如 `Thu, 30 Jul 2026 01:20:00 GMT`。
- 服务器系统时间必须正确，建议启用 NTP 时间同步。
- URL 查询参数必须 URL 编码，不能手工拼接未编码的空格、逗号、斜杠和等号。

### 3.3 Python 签名函数

```python
import base64
import hashlib
import hmac
import os
from email.utils import formatdate
from urllib.parse import urlencode, urlparse, urlunparse


def require_setting(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"缺少后端环境变量：{name}")
    return value


def build_signed_ws_url() -> str:
    base_url = os.getenv(
        "SCIPILOT_WS_URL",
        "wss://maas-api.cn-huabei-1.xf-yun.com/v1.1/chat",
    )
    api_key = require_setting("SCIPILOT_WS_API_KEY")
    api_secret = require_setting("SCIPILOT_WS_API_SECRET")

    parsed = urlparse(base_url)
    if parsed.scheme != "wss":
        raise RuntimeError("生产环境 SCIPILOT_WS_URL 必须使用 wss://")

    host = parsed.hostname
    path = parsed.path or "/"
    if not host:
        raise RuntimeError("SCIPILOT_WS_URL 缺少主机名")

    date = formatdate(timeval=None, localtime=False, usegmt=True)
    signature_origin = (
        f"host: {host}\n"
        f"date: {date}\n"
        f"GET {path} HTTP/1.1"
    )

    signature_sha = hmac.new(
        api_secret.encode("utf-8"),
        signature_origin.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    signature = base64.b64encode(signature_sha).decode("utf-8")

    authorization_origin = (
        f'api_key="{api_key}", algorithm="hmac-sha256", '
        f'headers="host date request-line", signature="{signature}"'
    )
    authorization = base64.b64encode(
        authorization_origin.encode("utf-8")
    ).decode("utf-8")

    query = urlencode(
        {
            "authorization": authorization,
            "date": date,
            "host": host,
        }
    )
    return urlunparse(
        (parsed.scheme, parsed.netloc, path, "", query, "")
    )
```

不要打印 `build_signed_ws_url()` 的返回值。它的查询字符串中含有短期有效的鉴权材料。

## 4. 请求消息

### 4.1 完整请求示例

WebSocket 握手成功后，发送一个合法 JSON 文本帧：

```json
{
  "header": {
    "app_id": "<SCIPILOT_WS_APP_ID>",
    "uid": "<不超过32字符的用户匿名标识>",
    "patch_id": [
      "<SCIPILOT_WS_RESOURCE_ID>"
    ]
  },
  "parameter": {
    "chat": {
      "domain": "<SCIPILOT_WS_MODEL_ID>",
      "temperature": 0.5,
      "top_k": 4,
      "max_tokens": 2048,
      "chat_id": "<用户下唯一的会话标识>",
      "search_disable": true,
      "show_ref_label": false,
      "enable_thinking": false
    }
  },
  "payload": {
    "message": {
      "text": [
        {
          "role": "system",
          "content": "你是 SciPilot 科研助手。"
        },
        {
          "role": "user",
          "content": "请说明迁移学习的基本流程。"
        }
      ]
    }
  }
}
```

`patch_id`、`domain` 与 APPID 必须来自匹配的服务配置。不要允许网页提交并覆盖这些字段。

### 4.2 `header` 参数

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `app_id` | string | 是 | 平台应用 APPID，官方限制最大 8 字符 |
| `uid` | string | 否 | 用户区分标识，最大 32 字符。建议后端生成不可逆、无直接个人信息的稳定标识 |
| `patch_id` | array | 微调模型是 | 数组元素为服务卡片的 `resourceId`；普通非微调模型不传 |

### 4.3 `parameter.chat` 参数

| 字段 | 类型 | 必填 | 默认或范围 | 说明 |
| --- | --- | --- | --- | --- |
| `domain` | string | 是 | 服务卡片的 `modelId` | 指定推理模型 |
| `temperature` | number | 否 | 通常 `[0,1]` | 控制随机性；官方当前默认值为 `0.7`，部分模型范围和默认值不同 |
| `top_k` | integer | 否 | `[1,6]`，默认 `4` | 从候选结果中采样 |
| `max_tokens` | integer | 否 | 默认 `2048` | 输入 token 与输出上限之和必须小于模型上下文长度 |
| `chat_id` | string | 否 | 用户下唯一 | 用于关联会话，不要复用到不同用户 |
| `search_disable` | boolean | 否 | 默认 `true` | `true` 表示关闭联网搜索 |
| `show_ref_label` | boolean | 否 | 默认 `false` | 联网搜索时是否返回信源信息 |
| `search_mode` | string | 否 | `normal` 或 `deep` | 联网搜索策略 |
| `response_format` | object | 否 | `{"type":"json_object"}` | JSON Mode；当前仅部分 DeepSeek R1/V3 模型支持 |
| `enable_thinking` | boolean | 否 | 默认 `false` | 开启深度思考；只对支持切换思考模式的模型有效 |
| `extra_body` | string | 否 | JSON 字符串 | 扩展参数。注意它是字符串，不是嵌套 JSON 对象 |

具体上下文长度、温度范围、深度思考和 JSON Mode 能力取决于微调模型的底座。未知时只发送最小参数集，不要假设所有底座都支持高级参数。

`extra_body` 的正确示例：

```json
{
  "parameter": {
    "chat": {
      "domain": "<SCIPILOT_WS_MODEL_ID>",
      "extra_body": "{\"reasoning_effort\":\"low\",\"stop\":[\"？\",\"结束\"]}"
    }
  }
}
```

当前资料列出的扩展参数：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `reasoning_effort` | string | 部分 OSS 模型支持 `low`、`medium`、`high`；是否生效取决于底座 |
| `stop` | string[] | 部分 DeepSeek V3/R1 模型支持，最多 4 个字符串 |
| `continue_final_message` | boolean | 部分 DeepSeek V3/R1 模型支持对最后一条 assistant 消息续写 |

### 4.4 `payload.message.text` 参数

`text` 是消息数组。每项包含：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `role` | string | 是 | `system`、`user` 或 `assistant` |
| `content` | string | 是 | 对应角色的文本内容 |

多轮对话示例：

```json
[
  {"role": "system", "content": "你是 SciPilot 科研助手。"},
  {"role": "user", "content": "什么是消融实验？"},
  {"role": "assistant", "content": "消融实验用于分析各模块对整体效果的贡献。"},
  {"role": "user", "content": "请给出一个实验设计模板。"}
]
```

普通对话的最后一条消息是当前 `user` 问题。历史消息必须由调用方一起传入并按上下文长度裁剪。官方页面给出了 8192 token 的有效输入限制提示，但不同模型的实际上下文可能不同，最终以服务卡片与模型说明为准。

## 5. 响应与结束条件

### 5.1 普通流式响应

服务通过多个 JSON 文本帧返回内容：

```json
{
  "header": {
    "code": 0,
    "message": "Success",
    "sid": "<本次调用的 sid>",
    "status": 1
  },
  "payload": {
    "choices": {
      "status": 1,
      "seq": 0,
      "text": [
        {
          "content": "模型本帧返回的增量文本",
          "index": 0,
          "role": "assistant"
        }
      ]
    }
  }
}
```

解析规则：

1. 每收到一个 WebSocket 文本帧，先执行 JSON 解析。
2. 检查 `header.code`；`0` 表示成功，非 `0` 表示业务错误。
3. 按 `payload.choices.seq` 顺序处理帧。
4. 将每帧 `payload.choices.text[*].content` 追加到最终回答。
5. 支持思考的模型可能返回 `reasoning_content`。它与最终 `content` 分开处理，默认不应直接展示或写入普通业务日志。
6. `payload.choices.status == 2` 或最终帧的 `header.status == 2` 表示本次回答结束。
7. `payload.usage.text` 通常只在最终帧返回。
8. 收到最终帧后主动发送正常 Close 帧并释放连接。

`header.status` 与 `payload.choices.status` 的状态含义：

| 值 | 含义 |
| --- | --- |
| `0` | 第一个结果／开始 |
| `1` | 中间结果／进行中 |
| `2` | 最后一个结果／结束 |

### 5.2 Token 用量

最终帧可能包含：

```json
{
  "completion_tokens": 80,
  "question_tokens": 20,
  "prompt_tokens": 100,
  "total_tokens": 180
}
```

路径为 `payload.usage.text`：

| 字段 | 说明 |
| --- | --- |
| `completion_tokens` | 回答消耗 token |
| `question_tokens` | 当前问题本身的 token，不包含历史 |
| `prompt_tokens` | 当前请求全部输入 token |
| `total_tokens` | 输入与回答 token 总量 |

### 5.3 联网搜索信源

当启用联网搜索并要求返回信源时，信源帧可能先于大模型文本到达，路径为：

```text
payload.plugins.text[*]
```

其中 `name` 常为 `ifly_search`，`content` 本身通常还是一个 JSON 字符串，需要再执行一次 JSON 解析。后端应先校验 URL 协议，仅向前端返回允许的 `http`/`https` 链接，并在页面中转义标题。

### 5.4 JSON Mode

JSON Mode 的 `content` 仍是流式增量数据。禁止逐帧调用 `JSON.parse`；必须先拼接全部 `content`，收到最终帧后再对完整字符串做一次 JSON 解析和业务 Schema 校验。

### 5.5 异常响应

```json
{
  "header": {
    "code": 10110,
    "message": "错误描述",
    "sid": "<本次调用的 sid>",
    "status": 2
  }
}
```

出现非零 `header.code` 时应停止拼接、记录 `code` 与 `sid`、向网页发送经过整理的错误提示，并关闭连接。不得把签名 URL或 APISecret 写入错误日志。

## 6. Python 后端直连示例

项目 `backend/requirements.txt` 已包含 `websocket-client`。以下示例适合先做服务器端联调：

```python
import json
import os
import uuid

from websocket import WebSocketTimeoutException, create_connection

# build_signed_ws_url 和 require_setting 使用第 3.3 节的实现。


def build_request(messages: list[dict], uid: str) -> dict:
    return {
        "header": {
            "app_id": require_setting("SCIPILOT_WS_APP_ID"),
            "uid": uid[:32],
            "patch_id": [require_setting("SCIPILOT_WS_RESOURCE_ID")],
        },
        "parameter": {
            "chat": {
                "domain": require_setting("SCIPILOT_WS_MODEL_ID"),
                "temperature": 0.5,
                "top_k": 4,
                "max_tokens": 2048,
                "chat_id": uuid.uuid4().hex,
                "search_disable": True,
                "show_ref_label": False,
                "enable_thinking": False,
            }
        },
        "payload": {
            "message": {
                "text": [
                    {"role": "system", "content": "你是 SciPilot 科研助手。"},
                    *messages,
                ]
            }
        },
    }


def call_scipilot_ws(user_message: str, uid: str) -> str:
    ws = None
    answer_parts: list[str] = []

    try:
        # 不要打印 signed_url。
        signed_url = build_signed_ws_url()
        ws = create_connection(signed_url, timeout=10)
        ws.settimeout(120)

        request = build_request(
            [{"role": "user", "content": user_message}],
            uid=uid,
        )
        ws.send(json.dumps(request, ensure_ascii=False))

        while True:
            raw = ws.recv()
            if not raw:
                raise RuntimeError("上游连接在最终帧前关闭")

            frame = json.loads(raw)
            header = frame.get("header", {})
            code = int(header.get("code", -1))
            sid = header.get("sid", "")

            if code != 0:
                message = header.get("message", "上游 WebSocket 调用失败")
                raise RuntimeError(f"上游错误 code={code}, sid={sid}: {message}")

            payload = frame.get("payload", {})
            choices = payload.get("choices") or {}

            for item in choices.get("text") or []:
                content = item.get("content") or ""
                if content:
                    answer_parts.append(content)
                    print(content, end="", flush=True)

            if choices.get("status") == 2 or header.get("status") == 2:
                usage = (payload.get("usage") or {}).get("text")
                if usage:
                    print(f"\nusage={usage}")
                break

        return "".join(answer_parts)

    except WebSocketTimeoutException as exc:
        raise RuntimeError("等待大模型响应超时") from exc
    finally:
        if ws is not None:
            ws.close()
```

联调调用：

```python
answer = call_scipilot_ws(
    user_message="请介绍你的科研辅助能力。",
    uid="server-generated-user-id",
)
```

## 7. FastAPI 网页代理设计

### 7.1 推荐的前后端消息协议

浏览器连接本站 `/ws/ai/chat` 后，只发送：

```json
{
  "messages": [
    {"role": "user", "content": "请解释注意力机制。"}
  ]
}
```

后端向浏览器发送统一事件，不要原样暴露上游协议：

```json
{"type":"delta","content":"增量文本"}
```

```json
{"type":"sources","items":[{"index":1,"url":"https://example.com","title":"信源标题"}]}
```

```json
{"type":"usage","prompt_tokens":100,"completion_tokens":80,"total_tokens":180}
```

```json
{"type":"done"}
```

```json
{"type":"error","code":10110,"message":"模型服务繁忙，请稍后重试","sid":"<sid>"}
```

这样可以让网页组件与上游厂商协议解耦，也能在后端统一过滤错误、信源和敏感字段。

### 7.2 FastAPI 核心代理示例

下面展示核心转发流程。`authenticate_websocket` 必须接入项目现有登录体系后再上线，不能删除。

```python
import asyncio
import json

import websockets
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


async def authenticate_websocket(client: WebSocket):
    """接入项目的 HttpOnly Cookie 或一次性 WebSocket ticket 校验。"""
    raise NotImplementedError("必须实现项目内 WebSocket 登录鉴权")


@router.websocket("/ws/ai/chat")
async def proxy_scipilot_chat(client: WebSocket):
    user = await authenticate_websocket(client)
    if user is None:
        await client.close(code=1008, reason="unauthorized")
        return

    await client.accept()

    try:
        browser_request = await asyncio.wait_for(
            client.receive_json(),
            timeout=15,
        )
        messages = browser_request.get("messages") or []

        # 正式代码应继续校验 role、消息数、单条长度和总 token。
        upstream_request = build_request(messages, uid=str(user.id))

        # 签名 URL 只在服务器内存中存在，禁止记录。
        async with websockets.connect(
            build_signed_ws_url(),
            open_timeout=10,
            close_timeout=3,
            ping_interval=None,
            max_size=2 * 1024 * 1024,
        ) as upstream:
            await upstream.send(
                json.dumps(upstream_request, ensure_ascii=False)
            )

            async for raw in upstream:
                frame = json.loads(raw)
                header = frame.get("header", {})
                payload = frame.get("payload", {})
                code = int(header.get("code", -1))

                if code != 0:
                    await client.send_json(
                        {
                            "type": "error",
                            "code": code,
                            "message": header.get("message", "模型服务调用失败"),
                            "sid": header.get("sid", ""),
                        }
                    )
                    await client.close(code=1011, reason="upstream error")
                    return

                plugin_items = (payload.get("plugins") or {}).get("text") or []
                for plugin in plugin_items:
                    if plugin.get("name") != "ifly_search":
                        continue
                    try:
                        sources = json.loads(plugin.get("content") or "[]")
                    except json.JSONDecodeError:
                        sources = []
                    if sources:
                        await client.send_json(
                            {"type": "sources", "items": sources}
                        )

                choices = payload.get("choices") or {}
                for item in choices.get("text") or []:
                    content = item.get("content") or ""
                    if content:
                        await client.send_json(
                            {"type": "delta", "content": content}
                        )

                if choices.get("status") == 2 or header.get("status") == 2:
                    usage = (payload.get("usage") or {}).get("text")
                    if usage:
                        await client.send_json({"type": "usage", **usage})
                    await client.send_json({"type": "done"})
                    await client.close(code=1000, reason="complete")
                    return

    except asyncio.TimeoutError:
        await client.send_json(
            {"type": "error", "message": "等待请求或模型响应超时"}
        )
        await client.close(code=1011, reason="timeout")
    except WebSocketDisconnect:
        # 离开上下文会关闭上游连接。
        return
    except Exception:
        # 详细异常只写入脱敏后的服务端日志。
        await client.close(code=1011, reason="internal error")
```

说明：

- `websockets` 通常随 `uvicorn[standard]` 安装；仍建议在依赖文件中显式固定兼容版本。
- 浏览器原生 WebSocket 不能像普通 Fetch 一样自由设置 Authorization 请求头。本站可使用同源 HttpOnly Cookie，或先通过 HTTPS 获取一次性短期 ticket，再进行 WebSocket 握手。
- 不建议把长期 Supabase access token 放在 URL 查询参数中，因为代理、浏览器历史和访问日志可能记录 URL。
- 示例采用“一次浏览器连接处理一次模型回答”的简单模式。若复用连接，同一连接上必须等待上一次回答的最终帧后才能发送下一次请求。
- 正式实现应同时监听浏览器断开事件；用户点击停止时立即关闭上游连接，避免继续消耗 token。

## 8. 浏览器调用本站 WebSocket

```javascript
function connectSciPilotChat(messages, handlers = {}) {
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(
    `${scheme}://${window.location.host}/ws/ai/chat`,
  );

  socket.addEventListener("open", () => {
    socket.send(JSON.stringify({ messages }));
  });

  socket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);

    if (message.type === "delta") {
      handlers.onText?.(message.content);
    } else if (message.type === "sources") {
      handlers.onSources?.(message.items);
    } else if (message.type === "usage") {
      handlers.onUsage?.(message);
    } else if (message.type === "done") {
      handlers.onDone?.();
      socket.close(1000, "complete");
    } else if (message.type === "error") {
      handlers.onError?.(new Error(message.message));
    }
  });

  socket.addEventListener("error", () => {
    handlers.onError?.(new Error("WebSocket 连接异常"));
  });

  return {
    cancel() {
      socket.close(1000, "user_cancel");
    },
  };
}

const chat = connectSciPilotChat(
  [{ role: "user", content: "请解释 Transformer。" }],
  {
    onText: (text) => console.log(text),
    onDone: () => console.log("回答完成"),
    onError: (error) => console.error(error),
  },
);

// “停止生成”按钮调用：chat.cancel();
```

前端不得提交或接收 APPID、APIKey、APISecret、签名 URL、`modelId`、`resourceId`。

## 9. 连接管理

- 使用 RFC6455 WebSocket 协议，生产环境只使用 `wss://`。
- 上游连续 60 秒无数据交互时可能主动断开。
- 同一连接在当前问题尚未完整返回前，不得发送下一个问题，否则可能收到 `10007`。
- 收到最终状态 `2` 后主动发送正常 Close 帧，不长期占用连接。
- 用户取消、页面卸载或本站客户端断开时，后端应同步关闭上游连接。
- 服务升级、熔断或网络波动可能主动断开连接；只有在尚未向网页输出任何正文时才适合透明重试。
- 已输出部分正文后不要自动重试，否则网页可能出现重复内容。可保留部分回答并提示用户重新生成。
- 不要通过持续空闲 ping 长期占用连接；官方错误码 `10018` 专门处理长时间只有 ping 而无实际请求的情况。

## 10. 常见错误码与处理

| code | 含义 | 建议处理 |
| --- | --- | --- |
| `0` | 成功 | 继续处理帧 |
| `10000` | WebSocket 升级错误 | 检查地址、代理和签名 URL |
| `10001` | 读取用户消息失败 | 检查连接和帧格式 |
| `10002` | 服务发送消息失败 | 记录 sid，必要时重试 |
| `10003` | 用户消息格式错误 | 检查 JSON 结构 |
| `10004` | Schema 错误 | 核对 `header/parameter/payload` 层级和类型 |
| `10005` | 参数值错误 | 核对范围、`modelId` 和 `resourceId` |
| `10006` | 同一用户并发连接冲突 | 限制用户并发，关闭旧连接 |
| `10007` | 上一问题尚未完成又发送新问题 | 等待最终帧后再发送 |
| `10008` | 服务容量不足 | 提示稍后重试并告警 |
| `10009`～`10012` | 引擎连接或内部错误 | 记录 sid，有限退避重试 |
| `10013` | 用户输入审核不通过 | 不重试，向用户展示合规提示 |
| `10014` | 回复内容审核不通过 | 清空本次已展示结果并提示用户 |
| `10016` | APPID 授权、额度或并发错误 | 检查授权、额度及并发配置 |
| `10018` | 长时间只有 ping、没有实际请求 | 不用 ping 长期占用空闲连接 |
| `10019` | 回复疑似敏感 | 展示风险提示，并按业务策略停止后续交互 |
| `10110` | 服务忙 | 在未输出正文时有限退避重试 |
| `10163` | 引擎参数 Schema 不通过 | 核对模型能力和请求参数 |
| `10222`、`10223` | 引擎网络或节点异常 | 有限退避重试并告警 |
| `10907` | Token 超过上限 | 裁剪历史、缩短输入或降低 `max_tokens` |
| `11200` | 未授权或业务量超限 | 检查服务授权与配额 |
| `11201` | 日流控超限 | 等待额度恢复或提升配额 |
| `11202` | 秒级流控超限 | 限流并稍后重试 |
| `11203` | 并发流控超限 | 降低并发或提升配额 |

错误日志建议只记录：时间、用户内部 ID、业务请求 ID、`header.code`、`header.sid`、耗时和已输出字符数。禁止记录签名 URL、APIKey、APISecret 和完整敏感对话。

## 11. 上线前检查清单

- [ ] 已轮换截图中暴露过的 WebSocket 认证信息。
- [ ] APPID、APIKey、APISecret 只存在于后端密钥环境。
- [ ] `SCIPILOT_WS_URL` 使用 `wss://`，地址与服务卡片一致。
- [ ] 签名原文使用当前 URL 的 host/path 和 `GET ... HTTP/1.1`。
- [ ] 服务器时间已通过 NTP 同步，签名 URL 每次连接前重新生成。
- [ ] `domain` 使用 `modelId`，`patch_id` 数组使用 `resourceId`。
- [ ] 浏览器只能连接本站 WebSocket，无法获得上游签名 URL。
- [ ] 本站 WebSocket 已接入登录鉴权、单用户并发限制和消息大小限制。
- [ ] 后端校验消息 role、条数、单条长度、总 token 和 `max_tokens`。
- [ ] 收到非零 `header.code` 时立即停止并关闭连接。
- [ ] 正确拼接所有 `content` 帧，并在最终状态 `2` 后主动关闭连接。
- [ ] JSON Mode 在最终帧后才做 JSON 解析和 Schema 校验。
- [ ] 页面“停止生成”会关闭本站与上游两个连接。
- [ ] 日志已对 URL 查询参数、凭据、Prompt 和模型结果进行脱敏。
- [ ] 已测试中文、多轮对话、长文本、取消、超时、断线、并发、审核与服务繁忙场景。

## 12. 联调顺序

1. 在后端环境配置六个 `SCIPILOT_WS_*` 变量。
2. 单独测试第 3.3 节签名函数，但不要打印或分享实际签名 URL。
3. 使用第 6 节服务器端示例完成一次问答，确认 APPID、modelId 与 resourceId 匹配。
4. 检查响应是否包含多个帧，并确认最后一帧状态为 `2`。
5. 接入 FastAPI WebSocket 路由和现有用户鉴权。
6. 连接网页端，确认浏览器网络面板中不存在讯飞凭据或上游签名 URL。
7. 完成异常、取消、并发和连接释放测试后再部署。

## 13. 参考资料

- [讯飞开放平台：推理服务 WebSocket 协议](https://www.xfyun.cn/doc/spark/%E6%8E%A8%E7%90%86%E6%9C%8D%E5%8A%A1-websocket.html)
- [讯飞开放平台：WebSocket 协议通用鉴权 URL 生成说明](https://www.xfyun.cn/doc/spark/general_url_authentication.html)
- 服务管控 → 模型服务列表 → SciPilot 服务卡片 → 调用信息（以控制台实时信息为准）
- 同目录 [SciPilot 微调大模型 HTTP 调用说明](./SciPilot微调大模型HTTP调用说明.md)
