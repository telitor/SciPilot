package cn.xfyun.chatdoc;

/** Unified exception for HTTP and API business failures. */
public final class XfyunApiException extends RuntimeException {
    private final Integer code;
    private final String sid;
    private final Integer httpStatus;

    public XfyunApiException(
            String message,
            Integer code,
            String sid,
            Integer httpStatus,
            Throwable cause
    ) {
        super(message, cause);
        this.code = code;
        this.sid = sid;
        this.httpStatus = httpStatus;
    }

    public Integer getCode() {
        return code;
    }

    public String getSid() {
        return sid;
    }

    public Integer getHttpStatus() {
        return httpStatus;
    }
}
