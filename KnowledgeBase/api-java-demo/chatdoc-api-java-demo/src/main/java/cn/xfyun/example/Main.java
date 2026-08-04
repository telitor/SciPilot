package cn.xfyun.example;

import cn.xfyun.chatdoc.XfyunKnowledgeBaseClient;
import com.google.gson.JsonObject;

import java.nio.file.Paths;
import java.time.Duration;
import java.util.Collections;
import java.util.List;

/** Minimal example; production code should inject one shared client instance. */
public final class Main {
    private Main() {
    }

    public static void main(String[] args) {
        if (args.length < 2) {
            System.err.println("用法: java ... <文件路径> <问题>");
            System.exit(2);
        }

        XfyunKnowledgeBaseClient client = XfyunKnowledgeBaseClient.fromEnvironment();
        String configuredRepoId = System.getenv("XFYUN_KB_REPO_ID");
        List<String> repoIds = configuredRepoId == null || configuredRepoId.trim().isEmpty()
                ? Collections.<String>emptyList()
                : Collections.singletonList(configuredRepoId.trim());

        JsonObject uploaded = client.uploadFile(Paths.get(args[0]), repoIds);
        String fileId = uploaded.getAsJsonObject("data").get("fileId").getAsString();
        client.waitUntilVectored(
                Collections.singletonList(fileId),
                Duration.ofMinutes(10),
                Duration.ofSeconds(3)
        );

        JsonObject request = client.buildChatRequest(
                Collections.singletonList(XfyunKnowledgeBaseClient.userMessage(args[1])),
                repoIds,
                repoIds.isEmpty() ? Collections.singletonList(fileId) : Collections.<String>emptyList()
        );
        client.chat(request, frame -> {
            if (!frame.has("status") || frame.get("status").getAsInt() != 99) {
                if (frame.has("content") && !frame.get("content").isJsonNull()) {
                    System.out.print(frame.get("content").getAsString());
                }
            }
        });
        System.out.println();
    }
}
