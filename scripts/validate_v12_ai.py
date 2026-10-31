"""Explicit live AI validation with labelled synthetic context and disposable local PostgreSQL.

Run only after the local test and browser gates pass. Makes one summary request,
then one stock follow-up, through the normal permission/budget/DeepSeek path.
Never connects to DATABASE_URL from environment, never runs against production.
"""
import json
from dataclasses import replace
from pathlib import Path
import secrets
import tempfile
import time

import httpx
import pgserver
from sqlalchemy import select

from alphalab.ai import AI
from alphalab.auth import Auth
from alphalab.config import Settings
from alphalab.db import metadata, engine_for, usage
from alphalab.repository import Repository
from alphalab.research_context import build_context


def synthetic_context():
    def data(rows):
        return {'items': rows, 'source': 'SYNTHETIC VALIDATION ONLY / 合成测试资料，非真实公司',
                'fetched_at': '2026-10-31T00:00:00+00:00', 'stale': False}
    context = build_context({'code': '000000', 'name': '合成研究验证公司（非上市公司）', 'exchange': 'SYNTHETIC',
                             'source': '合成验证资料，禁止当作真实公司'},
        data([{'行业': '合成验证行业', '上市时间': None}]),
        data([{'指标': name, '20260630': value} for name, value in
              [('营业收入(元)', 100000000), ('归母净利润(元)', -5000000), ('净资产收益率(ROE)(%)', -2),
               ('经营活动产生的现金流量净额(元)', 8000000), ('资产负债率(%)', 40)]]),
        data([{'date': '2026-10-29', 'close': 10}, {'date': '2026-10-30', 'close': 10.1}]),
        data([{'主营构成': '合成产品，仅用于接口验证', '分类类型': '按产品', '主营收入': 100000000,
               '报告日期': '2026-06-30'}]))
    context['validation_only'] = '全部内容为明确合成夹具；000000不是上市公司，不能映射到600519或任何真实公司。'
    return context


class ObservedClient(httpx.Client):
    observations = []
    def post(self, *args, **kwargs):
        started = time.perf_counter()
        response = super().post(*args, **kwargs)
        record = {'http_status': response.status_code, 'seconds': round(time.perf_counter()-started, 3),
                  'requested_model': kwargs['json']['model']}
        if response.is_success:
            body = response.json()
            record.update(response_model=body.get('model'), usage=body.get('usage'))
        self.observations.append(record)
        return response


def main():
    root = Path(__file__).resolve().parents[1]
    output = root/'test-results'/'v12-live-ai.json'
    output.parent.mkdir(exist_ok=True)
    base = Settings.load()  # Existing supported environment reader; values never printed.
    if not base.deepseek_api_key:
        result = {'status': 'blocked', 'reason': 'DEEPSEEK_API_KEY not configured', 'real_api_calls': 0}
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print(json.dumps(result, ensure_ascii=False))
        return 2
    pg = pgserver.get_server(Path(tempfile.mkdtemp(prefix='alphalab-v12-live-')), cleanup_mode='delete')
    url = pg.get_uri().replace('postgresql://', 'postgresql+psycopg://', 1)
    settings = replace(base, database_url=url, app_secret_key=secrets.token_hex(32), supabase_ca_cert='',
                       admin_phone='13800000009', admin_initial_password=secrets.token_urlsafe(24))
    db = engine_for(url)
    metadata.create_all(db)
    auth = Auth(settings)
    auth.bootstrap()
    repo = Repository(auth, auth.login(settings.admin_phone, settings.admin_initial_password))
    repo.put('user_preferences', 'profile', {'period': '长期', 'goal': '仅验证合成资料中的风险分析', 'level': '零基础'})
    ai = AI(repo, settings, ObservedClient)
    result = {'synthetic_only': True, 'code': '000000', 'baseline_total_tokens': 4532,
              'comparison_note': '旧请求资料未保存；与4532仅作总量参考，不是同Context对照。', 'calls': {}}
    for name in ('summary', 'followup'):
        try:
            if name == 'summary':
                report, cached = ai.company_summary(synthetic_context())
                assert not cached and set(report['report']) == {'summary'}
            else:ai.stock_followup(synthetic_context(), '这些明确合成资料中，负净利润和正经营现金流如何一起看？还缺什么证据？')
            record = dict(ObservedClient.observations[-1], status='passed')
            if name == 'summary':
                total = record['usage']['total_tokens']
                record.update(reduction_tokens=4532-total, reduction_percent=round((4532-total)/4532*100, 2))
            result['calls'][name] = record
        except Exception:
            # Never log exception text, credentials, response bodies or connection strings.
            result['calls'][name] = {'status': 'failed', 'reason': 'Request failed; details redacted',
                                     'observations': ObservedClient.observations[-1:]}
            break
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    with db.connect() as conn:
        result['settled_usage'] = [dict(row) for row in conn.execute(select(usage.c.input_tokens,
            usage.c.output_tokens, usage.c.status)).mappings()]
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['calls'].get('followup', {}).get('status') == 'passed' else 1


if __name__ == '__main__':raise SystemExit(main())
