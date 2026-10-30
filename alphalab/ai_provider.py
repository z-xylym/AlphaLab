"""DeepSeek transport only. Credentials stay in request headers, never in results or errors."""
import time
import httpx


class DeepSeekClient:
    def __init__(self, client_factory=httpx.Client):
        self.client_factory = client_factory

    def complete(self, key, model, system, content, max_tokens=2200, structured=False):
        payload = {'model': model, 'messages': [{'role': 'system', 'content': system},
                   {'role': 'user', 'content': content}], 'max_tokens': max_tokens, 'temperature': 0.2, 'stream': False}
        if structured:payload['response_format'] = {'type': 'json_object'}
        try:
            with self.client_factory(timeout=httpx.Timeout(60, connect=10)) as client:
                for attempt in range(2):
                    response = client.post('https://api.deepseek.com/chat/completions',
                                           headers={'Authorization': 'Bearer '+key}, json=payload)
                    if response.status_code != 429 or attempt:break
                    time.sleep(1)
                response.raise_for_status()
                result = response.json()
            answer = result['choices'][0]['message']['content']
            tokens = result['usage']
            inp, out = int(tokens['prompt_tokens']), int(tokens['completion_tokens'])
            if not isinstance(answer, str) or not answer.strip() or min(inp, out) < 0:raise ValueError()
            if key and key in answer:raise ValueError('credential echo')
            if result['choices'][0].get('finish_reason', 'stop') != 'stop':raise ValueError()
            return answer, inp, out
        except Exception:
            # Never propagate HTTP exceptions containing Authorization or provider response bodies.
            raise RuntimeError('AI服务请求未完成') from None
