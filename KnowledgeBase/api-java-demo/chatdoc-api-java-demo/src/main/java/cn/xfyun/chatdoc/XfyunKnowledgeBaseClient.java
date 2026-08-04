package cn.xfyun.chatdoc;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import okhttp3.FormBody;
import okhttp3.MediaType;
import okhttp3.MultipartBody;
import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.RequestBody;
import okhttp3.Response;
import okhttp3.ResponseBody;
import okio.BufferedSource;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Base64;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.concurrent.TimeUnit;
import java.util.function.Consumer;

/**
 * Reusable synchronous client for the iFlytek Spark Knowledge Base API.
 *
 * <p>Official documentation:
 * https://www.xfyun.cn/doc/spark/ChatDoc-API.html</p>
 */
public final class XfyunKnowledgeBaseClient {
    private static final MediaType JSON = MediaType.parse("application/json; charset=utf-8");
    private static final long MAX_FILE_BYTES = 20L * 1024L * 1024L;
    private static final Set<String> SUPPORTED_SUFFIXES = Collections.unmodifiableSet(
            new HashSet<String>(Arrays.asList(
                    "txt", "md", "doc", "docx", "pdf", "xls", "xlsx", "csv",
                    "jpg", "jpeg", "png", "bmp", "ppt", "pptx"
            ))
    );

    private final String appId;
    private final String apiSecret;
    private final String baseUrl;
    private final OkHttpClient httpClient;

    public XfyunKnowledgeBaseClient(String appId, String apiSecret) {
        this(appId, apiSecret, "https://chatdoc.xfyun.cn", defaultHttpClient());
    }

    public XfyunKnowledgeBaseClient(
            String appId,
            String apiSecret,
            String baseUrl,
            OkHttpClient httpClient
    ) {
        this.appId = requireText(appId, "appId");
        this.apiSecret = requireText(apiSecret, "apiSecret");
        this.baseUrl = requireText(baseUrl, "baseUrl").replaceAll("/+$", "");
        this.httpClient = httpClient;
    }

    public static XfyunKnowledgeBaseClient fromEnvironment() {
        String appId = System.getenv("XFYUN_KB_APP_ID");
        String apiSecret = System.getenv("XFYUN_KB_API_SECRET");
        String baseUrl = System.getenv("XFYUN_KB_BASE_URL");
        if (baseUrl == null || baseUrl.trim().isEmpty()) {
            baseUrl = "https://chatdoc.xfyun.cn";
        }
        if (appId == null || appId.trim().isEmpty()
                || apiSecret == null || apiSecret.trim().isEmpty()) {
            throw new IllegalStateException(
                    "缺少 XFYUN_KB_APP_ID 或 XFYUN_KB_API_SECRET 环境变量"
            );
        }
        return new XfyunKnowledgeBaseClient(appId, apiSecret, baseUrl, defaultHttpClient());
    }

    public JsonObject uploadFile(Path file, List<String> repoIds) {
        if (!Files.isRegularFile(file)) {
            throw new IllegalArgumentException("上传文件不存在: " + file);
        }
        validateUpload(file);
        MultipartBody.Builder body = new MultipartBody.Builder()
                .setType(MultipartBody.FORM)
                .addFormDataPart(
                        "file",
                        file.getFileName().toString(),
                        RequestBody.create(MediaType.parse("application/octet-stream"), file.toFile())
                )
                .addFormDataPart("parseType", "AUTO")
                .addFormDataPart("stepByStep", "false")
                .addFormDataPart("needSummary", "true");
        for (String repoId : safeList(repoIds)) {
            body.addFormDataPart("repoIds", repoId);
        }
        return executeJson(post("/openapi/v1/file/upload", body.build()));
    }

    public JsonObject uploadUrl(String sourceUrl, String fileName, List<String> repoIds) {
        validateFileName(fileName);
        MultipartBody.Builder body = new MultipartBody.Builder()
                .setType(MultipartBody.FORM)
                .addFormDataPart("url", requireText(sourceUrl, "sourceUrl"))
                .addFormDataPart("fileName", requireText(fileName, "fileName"))
                .addFormDataPart("parseType", "AUTO")
                .addFormDataPart("stepByStep", "false")
                .addFormDataPart("needSummary", "true");
        for (String repoId : safeList(repoIds)) {
            body.addFormDataPart("repoIds", repoId);
        }
        return executeJson(post("/openapi/v1/file/upload", body.build()));
    }

    public JsonObject fileStatus(List<String> fileIds) {
        List<String> ids = requireIds(fileIds, "fileIds");
        RequestBody body = new FormBody.Builder()
                .add("fileIds", String.join(",", ids))
                .build();
        return executeJson(post("/openapi/v1/file/status", body));
    }

    public JsonObject deleteFiles(List<String> fileIds) {
        List<String> ids = requireIds(fileIds, "fileIds");
        FormBody.Builder body = new FormBody.Builder();
        for (String fileId : ids) {
            body.add("fileIds", fileId);
        }
        return executeJson(post("/openapi/v1/file/del", body.build()));
    }

    public JsonObject waitUntilVectored(
            List<String> fileIds,
            Duration timeout,
            Duration pollInterval
    ) {
        List<String> ids = requireIds(fileIds, "fileIds");
        long deadline = System.nanoTime() + timeout.toNanos();
        while (true) {
            JsonObject response = fileStatus(ids);
            JsonArray data = response.has("data") && response.get("data").isJsonArray()
                    ? response.getAsJsonArray("data") : new JsonArray();
            int vectored = 0;
            List<String> failed = new ArrayList<String>();
            for (JsonElement element : data) {
                JsonObject item = element.getAsJsonObject();
                String status = stringValue(item, "fileStatus");
                String fileId = stringValue(item, "fileId");
                if ("vectored".equals(status) && ids.contains(fileId)) {
                    vectored++;
                } else if ("failed".equals(status)) {
                    failed.add(fileId);
                }
            }
            if (!failed.isEmpty()) {
                throw new XfyunApiException(
                        "文件处理失败: " + String.join(",", failed),
                        integerValue(response, "code"),
                        stringValue(response, "sid"),
                        200,
                        null
                );
            }
            if (vectored == ids.size()) {
                return response;
            }
            if (System.nanoTime() >= deadline) {
                throw new XfyunApiException(
                        "等待文件向量化超时", null, stringValue(response, "sid"), 200, null
                );
            }
            try {
                Thread.sleep(pollInterval.toMillis());
            } catch (InterruptedException error) {
                Thread.currentThread().interrupt();
                throw new XfyunApiException("等待文件向量化被中断", null, null, null, error);
            }
        }
    }

    public JsonObject createRepository(String name, String description, String tags) {
        JsonObject body = new JsonObject();
        body.addProperty("repoName", requireText(name, "repoName"));
        body.addProperty("repoDesc", description == null ? "" : description);
        body.addProperty("repoTags", tags == null ? "" : tags);
        return executeJson(postJson("/openapi/v1/repo/create", body));
    }

    public JsonObject addRepositoryFiles(String repoId, List<String> fileIds) {
        return repositoryFileOperation("/openapi/v1/repo/file/add", repoId, fileIds);
    }

    public JsonObject removeRepositoryFiles(String repoId, List<String> fileIds) {
        return repositoryFileOperation("/openapi/v1/repo/file/remove", repoId, fileIds);
    }

    public JsonObject deleteRepository(String repoId, boolean deleteFiles) {
        RequestBody body = new FormBody.Builder()
                .add("repoId", requireText(repoId, "repoId"))
                .build();
        String path = deleteFiles
                ? "/openapi/v1/repo/del-with-files"
                : "/openapi/v1/repo/del";
        return executeJson(post(path, body));
    }

    public JsonObject buildChatRequest(
            List<JsonObject> messages,
            List<String> repoIds,
            List<String> fileIds
    ) {
        List<String> repositories = safeList(repoIds);
        List<String> files = safeList(fileIds);
        if (repositories.isEmpty() == files.isEmpty()) {
            throw new IllegalArgumentException("repoIds 与 fileIds 必须且只能传一个");
        }
        if (messages == null || messages.isEmpty()) {
            throw new IllegalArgumentException("messages 不能为空");
        }

        JsonObject request = new JsonObject();
        request.add("repoIds", repositories.isEmpty() ? null : toJsonArray(repositories));
        request.add("fileIds", files.isEmpty() ? null : toJsonArray(files));
        request.remove(repositories.isEmpty() ? "repoIds" : "fileIds");
        request.addProperty("topN", 6);
        request.addProperty("thinkingOutput", false);
        JsonArray messageArray = new JsonArray();
        for (JsonObject message : messages) {
            messageArray.add(message);
        }
        request.add("messages", messageArray);

        JsonObject chatExtends = new JsonObject();
        chatExtends.addProperty("retrievalFilterPolicy", "REGULAR");
        chatExtends.addProperty("wikiPromptTpl", "根据知识库内容回答用户的问题");
        chatExtends.addProperty("temperature", 0.2);
        chatExtends.addProperty("outputType", "plain");
        request.add("chatExtends", chatExtends);
        return request;
    }

    public ChatResult chat(JsonObject requestBody, Consumer<JsonObject> onFrame) {
        Request request = signedRequestBuilder("/openapi/v2/chat")
                .addHeader("Accept", "text/event-stream")
                .post(RequestBody.create(JSON, requestBody.toString()))
                .build();
        StringBuilder content = new StringBuilder();
        StringBuilder reasoning = new StringBuilder();
        String sid = null;
        List<JsonObject> frames = new ArrayList<JsonObject>();
        List<JsonObject> references = new ArrayList<JsonObject>();

        try (Response response = httpClient.newCall(request).execute()) {
            if (!response.isSuccessful()) {
                ResponseBody errorBody = response.body();
                throw httpException(response, errorBody == null ? null : errorBody.string());
            }
            ResponseBody responseBody = response.body();
            if (responseBody == null) {
                throw new XfyunApiException("问答接口返回空响应", null, null, response.code(), null);
            }
            BufferedSource source = responseBody.source();
            String line;
            while ((line = source.readUtf8Line()) != null) {
                line = line.trim();
                if (line.isEmpty() || line.startsWith(":") || line.startsWith("event:")) {
                    continue;
                }
                if (line.startsWith("data:")) {
                    line = line.substring(5).trim();
                }
                if (line.isEmpty() || "[DONE]".equals(line)) {
                    continue;
                }
                JsonObject frame = JsonParser.parseString(line).getAsJsonObject();
                validateBusinessCode(frame, response.code());
                frames.add(frame);
                if (onFrame != null) {
                    onFrame.accept(frame);
                }
                if (frame.has("sid")) {
                    sid = stringValue(frame, "sid");
                }
                if (Integer.valueOf(99).equals(integerValue(frame, "status"))) {
                    references.add(frame);
                } else {
                    content.append(stringValue(frame, "content"));
                    reasoning.append(stringValue(frame, "reasoning_content"));
                }
            }
            return new ChatResult(
                    content.toString(), reasoning.toString(), sid, frames, references
            );
        } catch (IOException error) {
            throw new XfyunApiException("讯飞知识库问答请求失败", null, sid, null, error);
        }
    }

    public static JsonObject userMessage(String content) {
        JsonObject message = new JsonObject();
        message.addProperty("role", "user");
        message.addProperty("content", requireText(content, "content"));
        return message;
    }

    public static String makeSignature(String appId, String apiSecret, long timestamp) {
        try {
            MessageDigest md5 = MessageDigest.getInstance("MD5");
            byte[] digest = md5.digest(
                    (appId + timestamp).getBytes(StandardCharsets.UTF_8)
            );
            StringBuilder auth = new StringBuilder();
            for (byte value : digest) {
                auth.append(String.format("%02x", value & 0xff));
            }
            Mac mac = Mac.getInstance("HmacSHA1");
            mac.init(new SecretKeySpec(apiSecret.getBytes(StandardCharsets.UTF_8), "HmacSHA1"));
            byte[] signed = mac.doFinal(auth.toString().getBytes(StandardCharsets.UTF_8));
            return Base64.getEncoder().encodeToString(signed);
        } catch (Exception error) {
            throw new IllegalStateException("无法生成讯飞 API 签名", error);
        }
    }

    private JsonObject repositoryFileOperation(
            String path,
            String repoId,
            List<String> fileIds
    ) {
        List<String> ids = requireIds(fileIds, "fileIds");
        if (ids.size() > 20) {
            throw new IllegalArgumentException("单次最多操作 20 个文件");
        }
        JsonObject body = new JsonObject();
        body.addProperty("repoId", requireText(repoId, "repoId"));
        body.add("fileIds", toJsonArray(ids));
        return executeJson(postJson(path, body));
    }

    private Request postJson(String path, JsonObject body) {
        return post(path, RequestBody.create(JSON, body.toString()));
    }

    private Request post(String path, RequestBody body) {
        return signedRequestBuilder(path).post(body).build();
    }

    private Request.Builder signedRequestBuilder(String path) {
        long timestamp = System.currentTimeMillis() / 1000L;
        return new Request.Builder()
                .url(baseUrl + "/" + path.replaceFirst("^/+", ""))
                .addHeader("appId", appId)
                .addHeader("timeStamp", String.valueOf(timestamp))
                .addHeader("signature", makeSignature(appId, apiSecret, timestamp));
    }

    private JsonObject executeJson(Request request) {
        try (Response response = httpClient.newCall(request).execute()) {
            ResponseBody body = response.body();
            String text = body == null ? "" : body.string();
            if (!response.isSuccessful()) {
                throw httpException(response, text);
            }
            JsonObject payload = JsonParser.parseString(text).getAsJsonObject();
            validateBusinessCode(payload, response.code());
            return payload;
        } catch (XfyunApiException error) {
            throw error;
        } catch (Exception error) {
            throw new XfyunApiException("讯飞知识库 API 请求失败", null, null, null, error);
        }
    }

    private static void validateBusinessCode(JsonObject payload, int httpStatus) {
        Integer code = integerValue(payload, "code");
        if (code != null && code != 0) {
            String message = stringValue(payload, "desc");
            if (message.isEmpty()) {
                message = stringValue(payload, "message");
            }
            throw new XfyunApiException(
                    message.isEmpty() ? "讯飞知识库 API 调用失败" : message,
                    code,
                    stringValue(payload, "sid"),
                    httpStatus,
                    null
            );
        }
    }

    private static XfyunApiException httpException(Response response, String responseText) {
        Integer code = null;
        String sid = null;
        String message = "讯飞知识库 API HTTP " + response.code();
        if (responseText != null && !responseText.trim().isEmpty()) {
            try {
                JsonObject payload = JsonParser.parseString(responseText).getAsJsonObject();
                code = integerValue(payload, "code");
                sid = stringValue(payload, "sid");
                String apiMessage = stringValue(payload, "desc");
                if (apiMessage.isEmpty()) {
                    apiMessage = stringValue(payload, "message");
                }
                if (!apiMessage.isEmpty()) {
                    message = apiMessage;
                }
            } catch (RuntimeException ignored) {
                // Keep the sanitized HTTP message; do not expose credentials or raw HTML.
            }
        }
        return new XfyunApiException(message, code, sid, response.code(), null);
    }

    private static void validateUpload(Path file) {
        String name = file.getFileName().toString();
        validateFileName(name);
        try {
            if (Files.size(file) > MAX_FILE_BYTES) {
                throw new IllegalArgumentException("文档大小不能超过 20MB");
            }
        } catch (IOException error) {
            throw new IllegalArgumentException("无法读取上传文件: " + file, error);
        }
    }

    private static void validateFileName(String name) {
        requireText(name, "fileName");
        int dot = name.lastIndexOf('.');
        String suffix = dot >= 0 ? name.substring(dot + 1).toLowerCase() : "";
        if (!SUPPORTED_SUFFIXES.contains(suffix)) {
            throw new IllegalArgumentException("不支持的文档格式: " + suffix);
        }
    }

    private static JsonArray toJsonArray(List<String> values) {
        JsonArray array = new JsonArray();
        for (String value : values) {
            array.add(value);
        }
        return array;
    }

    private static List<String> safeList(List<String> values) {
        if (values == null) {
            return Collections.emptyList();
        }
        List<String> result = new ArrayList<String>();
        for (String value : values) {
            if (value != null && !value.trim().isEmpty()) {
                result.add(value.trim());
            }
        }
        return result;
    }

    private static List<String> requireIds(List<String> values, String name) {
        List<String> ids = safeList(values);
        if (ids.isEmpty()) {
            throw new IllegalArgumentException(name + " 不能为空");
        }
        return ids;
    }

    private static String requireText(String value, String name) {
        if (value == null || value.trim().isEmpty()) {
            throw new IllegalArgumentException(name + " 不能为空");
        }
        return value.trim();
    }

    private static String stringValue(JsonObject object, String name) {
        if (object == null || !object.has(name) || object.get(name).isJsonNull()) {
            return "";
        }
        return object.get(name).getAsString();
    }

    private static Integer integerValue(JsonObject object, String name) {
        if (object == null || !object.has(name) || object.get(name).isJsonNull()) {
            return null;
        }
        return object.get(name).getAsInt();
    }

    private static OkHttpClient defaultHttpClient() {
        return new OkHttpClient.Builder()
                .connectTimeout(10, TimeUnit.SECONDS)
                .readTimeout(10, TimeUnit.MINUTES)
                .build();
    }

    public static final class ChatResult {
        private final String content;
        private final String reasoningContent;
        private final String sid;
        private final List<JsonObject> frames;
        private final List<JsonObject> references;

        private ChatResult(
                String content,
                String reasoningContent,
                String sid,
                List<JsonObject> frames,
                List<JsonObject> references
        ) {
            this.content = content;
            this.reasoningContent = reasoningContent;
            this.sid = sid;
            this.frames = Collections.unmodifiableList(frames);
            this.references = Collections.unmodifiableList(references);
        }

        public String getContent() {
            return content;
        }

        public String getReasoningContent() {
            return reasoningContent;
        }

        public String getSid() {
            return sid;
        }

        public List<JsonObject> getFrames() {
            return frames;
        }

        public List<JsonObject> getReferences() {
            return references;
        }
    }
}
