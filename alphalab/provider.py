"""Run AKShare in a bounded child process so an upstream hang cannot stall Streamlit."""
import contextlib
import io
import json
import subprocess
import sys
import pandas as pd

def call(name, **kwargs):
    result=subprocess.run([sys.executable,'-m','alphalab.provider',name,json.dumps(kwargs)],
        capture_output=True,text=True,timeout=40,check=True)
    return pd.read_json(io.StringIO(result.stdout),orient='split',dtype=False)

if __name__=='__main__':
    allowed={'stock_zh_a_spot_em','stock_zh_a_spot','stock_zh_index_daily_em','stock_zh_a_hist',
        'stock_zh_a_daily','stock_individual_info_em','stock_financial_abstract',
        'stock_board_concept_name_em','stock_board_industry_name_em',
        'stock_board_concept_cons_em','stock_board_industry_cons_em','stock_zygc_em'}
    try:
        name=sys.argv[1]
        if name not in allowed:raise ValueError('Unsupported endpoint')
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            import requests
            from urllib.parse import urlparse
            original=requests.Session.request
            def verified_request(self,method,url,**kwargs):
                if url.startswith('http://'):
                    host=urlparse(url).hostname or ''
                    if host.endswith('.sina.com.cn') or host.endswith('.eastmoney.com'):
                        url='https://'+url[7:]
                    else:
                        raise ValueError('Untrusted plaintext endpoint')
                if kwargs.get('verify') is False:
                    raise ValueError('TLS verification must remain enabled')
                kwargs.setdefault('timeout',15)
                return original(self,method,url,**kwargs)
            requests.Session.request=verified_request
            import akshare
            frame=getattr(akshare,name)(**json.loads(sys.argv[2]))
        print(frame.to_json(orient='split',force_ascii=False,date_format='iso'))
    except Exception:
        # Never echo URLs, provider bodies, tokens, SQL or environment variables.
        raise SystemExit(1) from None
