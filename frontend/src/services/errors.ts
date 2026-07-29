import { isAxiosError } from 'axios';

interface FastAPIValidationIssue {
  type?: string;
  loc?: Array<string | number>;
  msg?: string;
  ctx?: Record<string, unknown>;
}

const FIELD_LABELS: Record<string, string> = {
  email: '邮箱',
  password: '密码',
  username: '用户名',
  confirm_password: '确认密码',
};

function fieldLabel(location?: Array<string | number>) {
  const field = location
    ?.filter((part) => part !== 'body')
    .map(String)
    .join('.');
  return field ? FIELD_LABELS[field] || field : '提交内容';
}

function validationMessage(issue: FastAPIValidationIssue) {
  const label = fieldLabel(issue.loc);
  const minLength = issue.ctx?.min_length;
  const maxLength = issue.ctx?.max_length;

  if (issue.type === 'string_too_short' && typeof minLength === 'number') {
    return `${label}至少需要 ${minLength} 个字符`;
  }
  if (issue.type === 'string_too_long' && typeof maxLength === 'number') {
    return `${label}不能超过 ${maxLength} 个字符`;
  }
  if (issue.msg?.includes('Password must contain at least one letter and one number')) {
    return '密码必须同时包含字母和数字';
  }
  if (issue.msg) {
    return `${label}：${issue.msg.replace(/^Value error,\s*/i, '')}`;
  }
  return `${label}格式不正确`;
}

/**
 * Convert FastAPI, Axios and network errors into one user-facing message.
 */
export function getApiErrorMessage(error: unknown, fallback = '请求失败，请稍后重试') {
  if (isAxiosError(error)) {
    if (error.code === 'ECONNABORTED') {
      return '请求超时，请检查后端服务后重试';
    }
    if (!error.response) {
      return '无法连接到后端服务，请确认本地服务已启动';
    }

    const detail = (error.response.data as { detail?: unknown } | undefined)?.detail;
    if (typeof detail === 'string' && detail.trim()) {
      return detail;
    }
    if (Array.isArray(detail)) {
      const messages = detail
        .filter((item): item is FastAPIValidationIssue => typeof item === 'object' && item !== null)
        .map(validationMessage);
      if (messages.length > 0) return messages.join('；');
    }
    if (
      typeof detail === 'object' &&
      detail !== null &&
      'message' in detail &&
      typeof detail.message === 'string'
    ) {
      return detail.message;
    }
    if (typeof error.message === 'string' && error.message.trim()) {
      return error.message;
    }
  }

  if (error instanceof Error && error.message.trim()) {
    return error.message;
  }
  return fallback;
}
