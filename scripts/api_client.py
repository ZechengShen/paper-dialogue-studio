"""Small OpenAI-compatible Chat Completions client; credentials stay out of artifacts."""
from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import dataclass, field, replace
from pathlib import Path
from urllib.parse import urlparse

from public_sources import request_public


class ApiError(ValueError):
    """A safe, user-facing error that never includes headers or raw response bodies."""


def load_environment(root):
    """Optional local .env, no shell expansion, only documented names, env takes priority."""
    path = Path(root) / '.env'
    allowed = {'MOONSHOT_API_KEY', 'LLM_API_KEY', 'LLM_BASE_URL', 'LLM_MODEL', 'NOTION_TOKEN', 'LLM_MAX_CALLS'}
    if path.is_file():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            name, sep, value = line.strip().partition('=')
            if sep and name in allowed:
                os.environ.setdefault(name, value.strip().strip('\"\''))


@dataclass(frozen=True)
class ApiSettings:
    base_url: str = 'https://api.moonshot.cn/v1'
    model: str = 'kimi-k3.1-pro'
    api_key: str = field(default='', repr=False)
    notion_token: str = field(default='', repr=False)
    max_calls: int = 32

    @classmethod
    def environment(cls):
        # Bad optional configuration must not prevent the Codex-only site from starting.
        try:
            max_calls = int(os.getenv('LLM_MAX_CALLS', '32'))
        except ValueError:
            max_calls = 32
        return cls(base_url=os.getenv('LLM_BASE_URL', cls.base_url), model=os.getenv('LLM_MODEL', cls.model),
                   api_key=os.getenv('LLM_API_KEY') or os.getenv('MOONSHOT_API_KEY', ''),
                   notion_token=os.getenv('NOTION_TOKEN', ''), max_calls=max_calls)

    def validate(self, require_key=True):
        parsed = urlparse(self.base_url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ApiError('API Base URL 必须是无账号密码、查询参数的 HTTPS 地址。')
        if not self.model.strip() or len(self.model) > 120 or not re.fullmatch(r'[A-Za-z0-9._:/-]+', self.model):
            raise ApiError('请输入平台支持的模型 ID。')
        if require_key and not self.api_key.strip():
            raise ApiError('请先在 API 设置中输入密钥，或配置本地 .env。')
        if any('\n' in value or '\r' in value for value in (self.api_key, self.notion_token)):
            raise ApiError('密钥不能包含换行。')
        if not 4 <= self.max_calls <= 80:
            raise ApiError('每任务调用上限需在 4–80 之间。')
        return self

    def public(self):
        return {'base_url': self.base_url, 'model': self.model, 'key_configured': bool(self.api_key),
                'notion_configured': bool(self.notion_token), 'max_calls': self.max_calls}


class SettingsStore:
    def __init__(self):
        self.lock = threading.Lock()
        self.value = ApiSettings.environment()

    def get(self):
        with self.lock:
            return self.value

    def update(self, data):
        with self.lock:
            changes = {key: str(data[key]).strip() for key in ('base_url', 'model') if key in data}
            if 'max_calls' in data:
                try:
                    changes['max_calls'] = int(data['max_calls'])
                except (TypeError, ValueError) as exc:
                    raise ApiError('API 调用上限必须是 4–80 之间的整数。') from exc
            for key in ('api_key', 'notion_token'):
                if data.get('clear_' + key):
                    changes[key] = ''
                elif data.get(key):
                    changes[key] = str(data[key]).strip()
            # Do not silently forward an existing key to a newly selected provider.
            if changes.get('base_url', self.value.base_url).rstrip('/') != self.value.base_url.rstrip('/') and not data.get('api_key'):
                changes['api_key'] = ''
            updated = replace(self.value, **changes).validate(require_key=False)
            self.value = updated
            return updated.public()


def decode_json(text):
    text = str(text).strip()
    if text.startswith('```'):
        text = re.sub(r'^```(?:json)?\s*|\s*```$', '', text)
    try:
        value = json.loads(text)
    except (ValueError, TypeError) as exc:
        raise ApiError('模型未返回完整 JSON；本次响应未发布，可保留材料重试。') from exc
    if not isinstance(value, dict):
        raise ApiError('模型 JSON 的顶层必须是对象。')
    return value


class ChatClient:
    def __init__(self, settings, cancel=None, transport=None):
        self.settings = settings.validate()
        self.cancel = cancel or threading.Event()
        self.transport = transport or request_public
        self.calls = 0
        self.usage = []

    def check(self):
        if self.cancel.is_set():
            raise ApiError('API 任务已停止，已有材料与阶段缓存保留。')

    def probe(self):
        """Read model metadata; does not submit documents or paid generation."""
        try:
            status, _, raw = self.transport(self.settings.base_url.rstrip('/') + '/models',
                headers={'Authorization': 'Bearer ' + self.settings.api_key}, timeout=20, limit=2*1024*1024)
        except (OSError, ValueError) as exc:
            raise ApiError('连接失败，请检查 Base URL、网络与防火墙。') from exc
        if status != 200:
            raise ApiError(f'模型列表接口返回 {status}，请检查密钥与平台权限。')
        try:
            models = [x['id'] for x in json.loads(raw).get('data', [])]
        except (KeyError, ValueError, TypeError) as exc:
            raise ApiError('模型列表接口格式不兼容。') from exc
        return {'connected': True, 'model_available': self.settings.model in models,
                'models': models[:200], 'message': '已连接；仅查询模型列表，尚未验证实际生成质量。'}

    def json(self, system, prompt, max_tokens=24000):
        self.check()
        if self.calls >= self.settings.max_calls:
            raise ApiError('达到本任务 API 调用上限；请检查阶段产物，调整上限后继续。')
        payload = {'model': self.settings.model, 'messages': [{'role': 'system', 'content': system},
                   {'role': 'user', 'content': prompt}], 'max_tokens': max_tokens,
                   'response_format': {'type': 'json_object'}, 'stream': False}
        headers = {'Authorization': 'Bearer ' + self.settings.api_key, 'Content-Type': 'application/json'}
        for attempt in range(3):
            self.check()
            if self.calls >= self.settings.max_calls:
                raise ApiError('达到本任务 API 调用上限，未继续请求。')
            self.calls += 1
            try:
                status, _headers, raw = self.transport(self.settings.base_url.rstrip('/') + '/chat/completions',
                    method='POST', headers=headers, body=json.dumps(payload).encode(), timeout=240, limit=16*1024*1024)
            except (OSError, ValueError) as exc:
                raise ApiError('无法连接模型 API；请检查网络、Base URL 或系统防火墙。未自动重复计费请求。') from exc
            self.check()
            if status in (429, 502, 503, 504) and attempt < 2:
                if self.cancel.wait(2 ** attempt):
                    self.check()
                continue
            if status >= 300:
                hints = {401: '密钥无效', 403: '无访问权限', 404: '模型或接口不存在',
                         429: '余额不足或触发限流', 400: '模型参数不兼容；请确认支持 JSON Mode 和 Chat Completions'}
                raise ApiError(f'API 返回 {status}：{hints.get(status, "服务暂不可用")}。')
            try:
                result = json.loads(raw)
                choice = result['choices'][0]
                self.usage.append(result.get('usage', {}))
                if choice.get('finish_reason') != 'stop':
                    raise ApiError('模型输出被截断或未正常结束；未把残缺内容当作完整结果。')
                return decode_json(choice['message']['content'])
            except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
                raise ApiError('API 响应格式不兼容 Chat Completions。') from exc
        raise ApiError('API 服务暂不可用。')
