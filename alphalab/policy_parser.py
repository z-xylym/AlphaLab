"""Official policy indexes: parse dated records, never infer publication dates from URLs."""
import json
import re
from datetime import date
from urllib.parse import urljoin,urlparse
from bs4 import BeautifulSoup

INDEX='https://www.gov.cn/zhengce/zuixin/'
DATE=re.compile(r'(20\d{2})\s*[-年/.]\s*(\d{1,2})\s*[-月/.]\s*(\d{1,2})日?')

def dated(value):
    match=DATE.search(str(value))
    if not match:return None
    try:return date(*map(int,match.groups())).isoformat()
    except ValueError:return None

def official(value,base=INDEX):
    if not isinstance(value,str) or not value.strip():return None
    url=urljoin(base,value.strip())
    if url.startswith('http://www.gov.cn/'):url='https://'+url[7:]
    parsed=urlparse(url)
    try:port=parsed.port
    except ValueError:return None
    if parsed.scheme=='https' and parsed.hostname=='www.gov.cn' and not parsed.username and port in (None,443):return url
    return None

def parse_index(content,base=INDEX):
    soup=BeautifulSoup(content,'html.parser');items={}
    def add(title,link,published):
        title=' '.join(str(title or '').split());link=official(link,base);published=dated(published)
        if not link or not published or len(title)<4 or not re.search(r'\.s?html?(?:$|[?#])',link):return
        # Index entry metadata only; never upgrade title text to verified policy measures.
        items[link]={'title':title,'url':link,'published_at':published,
            'publisher':'中国政府网（具体发文部门请核对原文）',
            'status':'征求意见' if '征求意见' in title else '待核对原文',
            'content':'官方索引记录；具体措施、发文部门及生效状态须另行核对原文。'}
    for a in soup.select('a[href]'):
        title=a.get('title') or a.get_text(' ',strip=True)
        published=a.get('data-date') or a.get('data-pubtime') or a.get('data-pubdate') or a.get('data-publish-date')
        parent=a.parent
        for _ in range(4):
            if published or parent is None:break
            # Never attach a page-level date to many unrelated links.
            links={x.get('href') for x in parent.select('a[href]')}
            if len(links)>1:break
            t=parent.find('time')
            # Dates in a headline are not publication metadata. Only inspect text outside links.
            outside=' '.join(str(text) for text in parent.find_all(string=True) if not text.find_parent('a'))
            dates={dated(match.group()) for match in DATE.finditer(outside)}-{None}
            published=(t.get('datetime') or t.get_text(' ',strip=True) if t else None) or parent.get('data-pubdate') or parent.get('data-pubtime') or parent.get('data-date') or (next(iter(dates)) if len(dates)==1 else None)
            parent=parent.parent
        add(title,a['href'],published)
    def walk(value,depth=0):
        if depth>12:return
        if isinstance(value,list):
            for row in value[:500]:walk(row,depth+1)
        elif isinstance(value,dict):
            fields={str(k).lower():v for k,v in value.items()}
            def first(names):return next((fields[x.lower()] for x in names if fields.get(x.lower()) is not None),'')
            add(first(('title','TITLE','headline','docTitle','DOCTITLE')),first(('url','URL','link','docUrl','DOCURL')),
                first(('datePublished','pubDate','pubtime','publishTime','publishedTime','published_at','publishDate','pub_date','publicationDate','发布日期','PUBDATE','DOCPUBTIME','DOCRELPUBTIME')))
            for row in value.values():
                if isinstance(row,(dict,list)):walk(row,depth+1)
    text=content.decode('utf-8',errors='replace') if isinstance(content,bytes) else content
    try:walk(json.loads(text))
    except (ValueError,TypeError):pass
    for script in soup.select('script'):
        raw=script.string or script.get_text()
        # JSON and JSON assignment only, never evaluate JavaScript.
        for start in [0]+[m.end() for m in re.finditer(r'=\s*(?=[\[{])',raw)][:4]:
            try:walk(json.JSONDecoder().raw_decode(raw[start:].lstrip())[0])
            except (ValueError,TypeError):pass
    resources=[]
    for node in soup.select('iframe[src],script[src]'):
        url=official(node.get('src'),base)
        if url and url not in resources and (node.name=='iframe' or any(k in url.lower() for k in ('/zhengce/','policy','zuixin','zcwj'))):resources.append(url)
    # Explicit same-origin JSON catalog references; do not follow arbitrary APIs or eval scripts.
    for value in re.findall(r'''["']([^"']+\.json(?:\?[^"']*)?)["']''',text):
        url=official(value,base)
        if url and url not in resources:resources.insert(0,url)
    return sorted(items.values(),key=lambda x:x['published_at'],reverse=True)[:20],resources[:3]
