"""Administer the candidate view without changing the immutable lexicon or either engine."""
import argparse
from contextlib import closing
import json
from pathlib import Path
import sys

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--root",type=Path,default=Path(__file__).resolve().parents[1])
    p.add_argument("--catalog",type=Path)
    s=p.add_subparsers(dest="operation",required=True)
    s.add_parser("verify")
    q=s.add_parser("lookup");q.add_argument("word");q.add_argument("--pending",action="store_true");q.add_argument("--view",type=int)
    q=s.add_parser("mention");q.add_argument("text");q.add_argument("--limit",type=int,default=5)
    q=s.add_parser("history");q.add_argument("id");q.add_argument("digest");q.add_argument("--release",choices=("r001","r002"),default="r002");q.add_argument("--view",type=int)
    for name in ("withdraw","restore"):
        q=s.add_parser(name);q.add_argument("selector",choices=("sense","batch"));q.add_argument("target");q.add_argument("--reason",required=True);q.add_argument("--request",required=True)
    a=p.parse_args();root=a.root.resolve(strict=True)
    sys.path.insert(0,str(root/"host"));import release25_lexicon as lex
    if a.operation=="verify":data=lex.verify_index(a.catalog)
    else:
        import service
        with closing(service.store()) as db:
            if a.operation=="lookup":data=lex.lookup(a.word,db=db,catalog_path=a.catalog,as_of=a.view,include_pending=a.pending)
            elif a.operation=="mention":data=lex.mention(a.text,a.limit,db=db,catalog_path=a.catalog)
            elif a.operation=="history":data=lex.resolve(a.id,a.digest,release_sha256=lex.BASE_PIN if a.release=="r001" else lex.RELEASE_PIN,db=db,catalog_path=a.catalog,as_of=a.view)
            else:
                with service.writer(),db:data=lex.change_view(db,a.selector,a.target,a.operation=="restore",a.reason,a.request,catalog_path=a.catalog)
    print(json.dumps(data,ensure_ascii=False,indent=2))
if __name__=="__main__":main()

