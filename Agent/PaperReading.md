# 论文精读 Agent 后端接入说明

本文档用于说明SciPilot后端如何调用讯飞星辰Agent智能体平台中Agent。前端不应直接持有或调用讯飞平台密钥，统一由后端代理调用。

## 1. 接入目标

后端接收前端聊天请求后，将用户问题转发给讯飞星辰Agent，并把 Agent 的流式回复整理后返回给前端，同时保存用户消息和 AI 回复。

建议后端对外仍保持当前业务接口：

```http
POST /chat
```

后端内部再调用讯飞星辰 WebSocket 接口。

## 2. 配置项

请将真实密钥放在后端 `.env` 中，不要写入 Git 仓库或前端代码。

```env
# 讯飞星辰 Agent
XF_AGENT_APP_ID=your_app_id
XF_AGENT_API_KEY=your_api_key
XF_AGENT_API_SECRET=your_api_secret
XF_AGENT_ASSISTANT_ID=your_assistant_id

# WebSocket 地址配置
XF_AGENT_WS_HOST=spark-openapi.cn-huabei-1.xf-yun.com
XF_AGENT_WS_PATH=/v1/assistants/{assistant_id}

# 模型对话参数
XF_AGENT_DOMAIN=generalv3
XF_AGENT_TEMPERATURE=0.5
XF_AGENT_TOP_K=4
XF_AGENT_MAX_TOKENS=2028
```

说明：

| 配置项 | 含义 | 是否必填 |
| --- | --- | --- |
| `XF_AGENT_APP_ID` | 讯飞开放平台申请的应用 `app_id` | 是 |
| `XF_AGENT_API_KEY` | 讯飞平台 APIKey | 是 |
| `XF_AGENT_API_SECRET` | 讯飞平台 API Secret，用于生成签名 | 是 |
| `XF_AGENT_ASSISTANT_ID` | 论文精读 Agent 的智能体 ID | 是 |
| `XF_AGENT_WS_HOST` | WebSocket 域名 | 是 |
| `XF_AGENT_WS_PATH` | WebSocket 路径，需替换 `{assistant_id}` | 是 |
| `XF_AGENT_DOMAIN` | 使用的模型领域，通用模型通常为 `generalv3` | 是 |
| `XF_AGENT_TEMPERATURE` | 采样阈值，范围 `(0, 1]`，越大随机性越强 | 否 |
| `XF_AGENT_TOP_K` | 从 `k` 个候选中随机选一个，范围 `1-6` | 否 |
| `XF_AGENT_MAX_TOKENS` | 回答最大 token 数，范围 `1-4096` | 否 |

## 3. 讯飞接口信息

### 3.1 请求方法和 URL

接口类型：流式 WebSocket。

原始地址：

```text
wss://spark-openapi.cn-huabei-1.xf-yun.com/v1/assistants/{assistant_id}
```

调用时需要将 `{assistant_id}` 替换为平台提供的论文精读 Agent ID，并在 URL 查询参数中追加鉴权字段。

带鉴权参数后的形式：

```text
wss://spark-openapi.cn-huabei-1.xf-yun.com/v1/assistants/{assistant_id}?authorization={authorization}&date={date}&host={host}
```

每次交互都需要重新建立 WebSocket 连接。单次交互结束后，服务端会主动断开连接。如果后端需要中止生成，可以主动关闭 WebSocket 连接。

### 3.2 鉴权要求

讯飞平台使用签名机制鉴权。后端需要基于 `APIKey` 和 `API Secret` 生成 WebSocket 连接 URL。

常见签名字段：

| 字段 | 来源 | 说明 |
| --- | --- | --- |
| `host` | `spark-openapi.cn-huabei-1.xf-yun.com` | 请求域名 |
| `date` | 当前 GMT 时间 | RFC1123 格式，例如 `Wed, 08 Jul 2026 05:20:00 GMT` |
| `authorization` | 后端计算生成 | HMAC-SHA256 签名后再 Base64 编码 |

签名生成逻辑应以讯飞平台「鉴权说明」为准。若采用讯飞 WebSocket 通用 HMAC-SHA256 签名方式，签名原文通常由以下三行组成：

```text
host: spark-openapi.cn-huabei-1.xf-yun.com
date: {date}
GET /v1/assistants/{assistant_id} HTTP/1.1
```

再使用 `API Secret` 对签名原文进行 HMAC-SHA256，得到签名值，组装如下授权原文：

```text
api_key="{APIKey}", algorithm="hmac-sha256", headers="host date request-line", signature="{signature}"
```

最后将授权原文 Base64 编码，作为 URL 查询参数 `authorization`。

注意：

| 注意事项 | 说明 |
| --- | --- |
| 时间格式 | `date` 必须是 GMT/RFC1123 格式，避免本地时区格式 |
| 路径一致 | 签名中的 request-line 路径必须和实际 WebSocket 路径一致 |
| 密钥位置 | `API Secret` 只允许后端读取，不允许返回给前端 |
| 权限 | 默认 `APPID` 没有使用权限时，会返回流控或权限相关错误 |

## 4. 请求协议

WebSocket 建连成功后，后端向服务端发送一条 JSON 消息。

### 4.1 请求 JSON 示例

```json
{
  "header": {
    "app_id": "your_app_id",
    "uid": "user_123456"
  },
  "parameter": {
    "chat": {
      "domain": "generalv3",
      "temperature": 0.5,
      "top_k": 4,
      "max_tokens": 2028
    }
  },
  "payload": {
    "message": {
      "text": [
        {
          "role": "user",
          "content": "请精读这篇论文的 Abstract 和 Introduction，并总结研究问题、方法思路和创新点。"
        }
      ]
    }
  }
}
```

### 4.2 请求字段说明

| 字段 | 类型 | 是否必填 | 说明 |
| --- | --- | --- | --- |
| `header.app_id` | string | 是 | 讯飞开放平台应用 `app_id`，最大长度 8 |
| `header.uid` | string | 否 | 用户 ID，最大长度 32，用于后续扩展和排查问题 |
| `parameter.chat` | object | 是 | 对话参数 |
| `parameter.chat.domain` | string | 是 | 使用的领域，通用模型通常为 `generalv3` |
| `parameter.chat.temperature` | float | 否 | 随机性控制，默认可设为 `0.5` |
| `parameter.chat.top_k` | int | 否 | 候选采样数量，默认可设为 `4` |
| `parameter.chat.max_tokens` | int | 否 | 回答最大长度，建议不超过 `4096` |
| `payload.message.text` | array | 是 | 对话消息数组 |
| `payload.message.text[].role` | string | 是 | 角色，取值 `user` 或 `assistant` |
| `payload.message.text[].content` | string | 是 | 该角色的对话内容 |

单轮交互只需要传递一个 `user` 角色数据：

```json
[
  {
    "role": "user",
    "content": "你会做什么？"
  }
]
```

文本有效内容不能超过 8192 token。后端应在调用前对超长论文内容做截断、摘要或分段处理。

## 5. 响应协议

讯飞接口是流式返回。后端需要持续接收 WebSocket 消息，并按顺序拼接 `payload.choices.text[].content`。

### 5.1 正常响应示例

```json
{
  "header": {
    "code": 0,
    "message": "Success",
    "sid": "cht000704fa@dx16ade44e4d87a1c802",
    "status": 0
  },
  "payload": {
    "choices": {
      "status": 2,
      "seq": 0,
      "text": [
        {
          "content": "这是 AI 的回复文本",
          "index": 0,
          "role": "assistant"
        }
      ]
    },
    "usage": {
      "text": {
        "completion_tokens": 0,
        "question_tokens": 0,
        "prompt_tokens": 0,
        "total_tokens": 0
      }
    }
  }
}
```

### 5.2 响应字段说明

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `header.code` | int | 服务错误码，`0` 表示正常，非 `0` 表示出错 |
| `header.message` | string | 返回消息描述，出错时为错误描述 |
| `header.sid` | string | 会话 ID，可用于日志排查 |
| `header.status` | int | 会话状态，`0` 首个结果，`1` 中间结果，`2` 最后一个结果 |
| `payload.choices.status` | int | 文本数据状态，`0` 开始，`1` 生成中，`2` 结束 |
| `payload.choices.seq` | int | 数据序号 |
| `payload.choices.text` | array | 文本结果数组 |
| `payload.choices.text[].content` | string | 当前片段的回复内容 |
| `payload.choices.text[].role` | string | 通常为 `assistant` |
| `payload.usage.text` | object | token 消耗信息，通常只在最后一个结果中返回 |

### 5.3 异常响应示例

```json
{
  "header": {
    "code": 10110,
    "message": "xxxx",
    "sid": "cht00120013@dx181c8172afb0001102",
    "status": 2
  }
}
```

后端处理规则：

| 场景 | 处理方式 |
| --- | --- |
| `header.code == 0` | 正常解析并拼接回复 |
| `header.code != 0` | 记录 `code`、`message`、`sid`，向前端返回后端统一错误 |
| `header.status == 2` 或 `payload.choices.status == 2` | 表示本轮生成结束，可以关闭连接 |
| WebSocket 连接异常 | 记录异常，返回 `LLM call failed` 或项目统一错误码 |
| 用户主动取消 | 后端主动关闭 WebSocket 连接 |

## 6. 后端集成流程

建议后端 `/chat` 接口保持当前业务流程：

```text
1. 校验当前用户身份
2. 校验 conversation 是否属于当前用户
3. 校验 agent 是否存在
4. 保存用户消息
5. 调用讯飞星辰论文精读 Agent
6. 拼接并保存 assistant 回复
7. 更新 conversation 时间和标题
8. 返回 assistant 回复给前端
```

内部调用讯飞 Agent 的建议伪代码：

```python
async def call_paper_reading_agent(user_id: str, user_message: str) -> str:
    ws_url = build_xf_agent_ws_url(
        host=XF_AGENT_WS_HOST,
        path=f"/v1/assistants/{XF_AGENT_ASSISTANT_ID}",
        api_key=XF_AGENT_API_KEY,
        api_secret=XF_AGENT_API_SECRET,
    )

    request_payload = {
        "header": {
            "app_id": XF_AGENT_APP_ID,
            "uid": normalize_uid(user_id),
        },
        "parameter": {
            "chat": {
                "domain": XF_AGENT_DOMAIN,
                "temperature": XF_AGENT_TEMPERATURE,
                "top_k": XF_AGENT_TOP_K,
                "max_tokens": XF_AGENT_MAX_TOKENS,
            }
        },
        "payload": {
            "message": {
                "text": [
                    {
                        "role": "user",
                        "content": user_message,
                    }
                ]
            }
        },
    }

    answer_parts = []

    async with websockets.connect(ws_url) as websocket:
        await websocket.send(json.dumps(request_payload, ensure_ascii=False))

        async for raw_message in websocket:
            data = json.loads(raw_message)

            header = data.get("header", {})
            if header.get("code") != 0:
                raise RuntimeError(
                    f"Xunfei agent error: code={header.get('code')}, "
                    f"message={header.get('message')}, sid={header.get('sid')}"
                )

            choices = data.get("payload", {}).get("choices", {})
            for item in choices.get("text", []):
                answer_parts.append(item.get("content", ""))

            if header.get("status") == 2 or choices.get("status") == 2:
                break

    return "".join(answer_parts)
```

## 7. 与当前后端代码的衔接建议

当前后端的 AI 调用入口是：

```text
backend/services/llm_service.py
```

建议新增一个专门的服务文件：

```text
backend/services/xunfei_agent_service.py
```

然后在 `backend/services/llm_service.py` 中按 Agent 类型路由：

```python
def generate_reply(system_prompt: str, user_message: str, agent_category: str = "") -> str:
    if agent_category == "paper-reading":
        return call_paper_reading_agent_sync(user_message)

    return call_default_llm(system_prompt, user_message)
```

如果第一版只接入论文精读 Agent，也可以直接将 `/chat` 中的 `generate_reply(...)` 替换为讯飞 Agent 调用。

## 8. 推荐返回给前端的数据

如果后端暂时不做流式转发，可以将讯飞流式结果拼接完后再返回：

```json
{
  "reply": "论文精读 Agent 的完整回复文本"
}
```

如果后续需要前端打字机效果，后端可以把讯飞 WebSocket 的片段转成 SSE 或后端 WebSocket 再转发给前端。

## 9. 测试用例

### 9.1 最小测试问题

```text
你是谁？你可以帮助我完成哪些论文精读任务？
```

预期：返回论文精读 Agent 的能力说明。

### 9.2 论文精读测试问题

```text
请精读以下论文摘要，并从研究背景、研究问题、方法思路、创新点、不足和可复现方向六个方面进行分析：

{论文摘要文本}
```

预期：返回结构化分析结果，至少包含背景、问题、方法、创新点、不足、复现建议。

## 10. 安全要求

| 要求 | 说明 |
| --- | --- |
| 密钥只放后端 | `APIKey`、`API Secret` 不得暴露给前端 |
| `.env` 不提交 | 真实 `.env` 文件不要提交到 Git |
| 日志脱敏 | 日志中不要打印完整 `authorization`、`APIKey`、`API Secret` |
| 用户输入限制 | 对超长论文文本做长度限制，避免超过 8192 token |
| 错误统一封装 | 不建议把讯飞原始错误堆栈直接返回给前端 |
| uid 限长 | `header.uid` 最大长度 32，建议使用用户 ID 的短哈希 |

## 11. 后端接入检查清单

- [ ] 已在讯飞平台确认 `APPID` 对该 Agent 有调用权限
- [ ] 已拿到论文精读 Agent 的 `assistant_id`
- [ ] 已将 `APPID`、`APIKey`、`API Secret` 写入后端 `.env`
- [ ] 已实现 WebSocket URL 签名函数
- [ ] 已实现请求 JSON 组装
- [ ] 已实现流式响应拼接
- [ ] 已处理 `header.code != 0` 的错误情况
- [ ] 已接入 `/chat` 保存消息流程
- [ ] 已完成最小测试问题调用
