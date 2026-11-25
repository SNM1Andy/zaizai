"""Find an attributed definition in the local curriculum. A match is not an assertion about the world."""
import hashlib,json,re
from functools import lru_cache
import unicodedata
def norm(s):return "".join(re.findall(r"[\u3400-\u9fffA-Za-z0-9]+",unicodedata.normalize("NFKC",s).casefold()))
def grams(s):
    s=norm(s)
    return {s[i:i+2] for i in range(len(s)-1)}
def find(db,text):
    t=text.strip().rstrip("？?。!！ ")
    choices=[r"(?:你能不能|能不能|能否|可不可以|可以|能|请|麻烦)?(?:给我|帮我)?(?:说说|讲一下|讲讲|解释一下|解释|介绍一下|介绍|说明)(.{2,45}?)(?:的意思|是什么意思|吗|么)?",
             r"(.{2,45}?)(?:是怎么回事|指的是什么|指什么|是什么东西|是什么意思|到底是什么意思|是什么|怎么理解)",
             r"(?:我想知道|请问)?(?:什么是|什么叫)(.{2,45})"]
    term=None
    for pattern in choices:
        m=re.fullmatch(pattern,t)
        if m:term=m[1].strip("「」“”《》 ：:");break
    if not term or any(w in term for w in ("忽略规则","把它当事实","直接批准","执行代码")):return None
    term=norm(term);words=grams(term)
    if len(term)<2 or not words:return None
    ranks=[]
    for row in db.execute("SELECT id,title,body,boundary,source,version FROM study3_card"):
        title=norm(row["title"]);title_words=grams(title)
        exact=bool(term==title);contained=bool((len(term)>=3 and term in title) or (len(title)>=3 and title in term))
        overlap=words&title_words
        if not(exact or contained or (len(overlap)>=2 and len(overlap)/len(words)>=.66)):continue
        score=2*exact+float(contained)+len(overlap)/(len(words|title_words) or 1)
        ranks.append((score,dict(row)))
    ranks.sort(key=lambda x:(-x[0],x[1]["id"]))
    if not ranks:return None
    return [row for score,row in ranks[:4] if ranks[0][0]-score<=.18]

def attribute(rows):
    if len(rows)>1:
        return "课本中有几项可能相关："+ "；".join(x["id"]+" "+x["title"] for x in rows)+"。你想先看哪一课？"
    x=rows[0]
    return f"按《{x['title']}》的说明，{x['body'][:400]}\n适用范围：{x['boundary'][:160]}\n出处：学习卡 {x['id']}。"

