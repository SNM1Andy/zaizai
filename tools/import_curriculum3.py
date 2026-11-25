"""Inspect and transactionally register the supplied 33-book course; never execute packaged material."""
from argparse import ArgumentParser
from collections import Counter
from contextlib import closing
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import time
from zipfile import ZipFile

ROOT=Path(__file__).resolve().parents[1]
ARCHIVE=Path.home()/"Downloads/zaizai_curriculum_complete.zip"
PACKAGE_PIN="4c94d89651fc34a401e812943476e961d309e0ed47ff9e145f31a5ebb31ac2d9"
PREFIX="zaizai_curriculum/"
CORPUS=PREFIX+"zaizai-curriculum-corpus.jsonl"
HEADER=re.compile(r"^### (M\d{2}-[GM]\d-\d{2})｜(.+?)\s*$")
FIELD=re.compile(r"^\s*-\s+\*\*(定义|类型|适用边界|版本与状态)\*\*\s*[：:]\s*(.+?)\s*$")
TITLE_ALIAS={
    "100以内加减与守恒":"100以内加减与数量守恒",
    "认识人民币面值与等价交换":"认识货币面值与等价交换",
    "零花钱有限与二选一取舍":"有限预算与二选一取舍"
}
def check(ok,message):
    if not ok:raise ValueError(message)

def enc(obj):
    return json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(",",":"))

def sha(data):return sha256(data).hexdigest()

def read_book(path):
    check(path.stat().st_size<=4_000_000,"教材包超出本版本格式上限")
    data=path.read_bytes();pin=sha(data)
    check(pin==PACKAGE_PIN,"教材包与这版核验过的 308 课版本不符；新版本需先核对课程及测试边界")
    lessons=[];counts=Counter()
    with ZipFile(BytesIO(data)) as archive:
        names=archive.namelist()
        check(len(names)==36==len(set(names)),"文件数量或唯一性不符")
        check(sum(i.file_size for i in archive.infolist())<2_000_000,"教材展开大小不符")
        indexed=[json.loads(line) for line in archive.read(CORPUS).decode("utf-8-sig").splitlines() if line.strip()]
        check(len(indexed)==300 and len({r["id"] for r in indexed})==300,"结构化索引不完整")
        check(all(r["candidate_only"] is True and r["modify_emotion_module"] is False for r in indexed),"候选材料范围不一致")
        for name in sorted(names):
            m=re.fullmatch(r"zaizai_curriculum/(0[1-7])_[^/]+/([GM][1-5])(?:_[^/]+)?\.md",name)
            if not m:continue
            unit,grade=m.groups();raw=archive.read(name)
            lines=raw.decode("utf-8-sig").splitlines()
            marks=[(i,h[1],h[2]) for i,line in enumerate(lines) if (h:=HEADER.fullmatch(line))]
            for j,(at,key,title) in enumerate(marks):
                check(key.startswith("M"+unit+"-"+grade+"-"),"册与课号不符："+key)
                stop=marks[j+1][0] if j+1<len(marks) else len(lines)
                section=lines[at:stop]
                fields={}
                for line in section:
                    if found:=FIELD.fullmatch(line):
                        check(found[1] not in fields,"课内字段重号："+key)
                        fields[found[1]]=found[2].strip().strip(chr(96))
                check(set(fields)=={"定义","类型","适用边界","版本与状态"},"课程定义或边界缺失："+key)
                index_id=None;index_title=None
                if grade[0]=="G":
                    n=(int(unit)-1)*50+(int(grade[1])-1)*10+int(key[-2:])
                    ix=indexed[n-1]
                    check(ix["id"]==f"CUR-{n:03}" and ix["grade_tier"]==grade,"教材与 JSONL 年级或索引冲突")
                    original_title=ix["topic"]
                    check(TITLE_ALIAS.get(original_title,original_title)==title,"教材与索引标题不符："+key)
                    index_id=ix["id"];index_title=original_title
                lessons.append({"id":key,"title":title,"subject":name.split("/")[1],"grade":grade,
                    "definition":fields["定义"],"type":fields["类型"],"scope":fields["适用边界"],
                    "candidate_version":fields["版本与状态"],"index_id":index_id,"index_title":index_title,
                    "book":name.removeprefix(PREFIX),"book_sha256":sha(raw),"lines":[at+1,stop],
                    "lesson_sha256":sha(("\n".join(section)+"\n").encode())})
                counts[unit]+=1
    check(len(lessons)==len({r["id"] for r in lessons})==308 and sorted(counts.values())==[8,50,50,50,50,50,50],"课本覆盖不完整")
    return pin,lessons

def material_files(pin,lessons):
    contents="".join(enc(x)+"\n" for x in lessons).encode()
    manifest=dict(package_sha256=pin,books=len({x["book"] for x in lessons}),lessons=len(lessons),
                  structured_index=sum(x["index_id"] is not None for x in lessons),
                  meta_lessons=sum(x["index_id"] is None for x in lessons),title_aliases=TITLE_ALIAS,
                  stage_limit=2,heldout_exams=0,admitted="课名、定义、类型、边界及定位",
                  corpus_role="前 300 课的检索索引，MD 正文为课文来源",catalog_sha256=sha(contents))
    index=["# 再再正式课本目录","","在再再中输入“学习卡 课号”即可查定义、来源与边界。四值例题带有公开训练标签，本批课程的最高自动阶段为可据来源复述。",""]
    book=""
    for x in lessons:
        if x["book"]!=book:
            book=x["book"];index+=["","## "+book.removesuffix(".md"),""]
        index.append("- "+x["id"]+"　"+x["title"])
    return {"candidate-lessons.jsonl":contents,"manifest.json":(enc(manifest)+"\n").encode(),
            "目录.md":("\n".join(index)+"\n").encode()}

def materialize(folder,files):
    folder.mkdir(parents=True,exist_ok=True)
    for name,data in files.items():
        dest=folder/name
        if dest.exists():
            check(dest.read_bytes()==data,"保存的教材材料摘要冲突："+name);continue
        with tempfile.NamedTemporaryFile(dir=folder,delete=False) as f:
            tmp=Path(f.name);f.write(data);f.flush();os.fsync(f.fileno())
        try:
            try:os.rename(tmp,dest)
            except FileExistsError:
                check(dest.read_bytes()==data,"并发保存的教材材料冲突")
        finally:tmp.unlink(missing_ok=True)

def comparison(db,lessons):
    old={r["id"]:dict(r) for r in db.execute("SELECT id,title,version,level,target,kind,body,boundary,source,locator FROM study3_card")}
    ids={r["id"] for r in lessons};titles={r["title"] for r in lessons}
    other=[x for k,x in old.items() if k not in ids]
    return old,dict(existing_cards=len(old),other_cards=len(other),exact_title_overlaps_with_other=sorted({r["title"] for r in other}&titles),
                    already_present=sum(k in old for k in ids),would_insert=sum(k not in old for k in ids))

def apply(db,pin,lessons,folder,archive_name):
    db.execute("BEGIN IMMEDIATE")
    try:
        old,report=comparison(db,lessons)
        db.execute("""CREATE TABLE IF NOT EXISTS curriculum3_release
            (pin TEXT PRIMARY KEY,archive_name TEXT NOT NULL,material TEXT NOT NULL,catalog_sha256 TEXT NOT NULL,registered REAL NOT NULL)""")
        db.execute("""CREATE TABLE IF NOT EXISTS curriculum3_lesson
            (id TEXT PRIMARY KEY,package_pin TEXT NOT NULL,book TEXT NOT NULL,book_sha256 TEXT NOT NULL,
             line_first INTEGER NOT NULL,line_last INTEGER NOT NULL,index_id TEXT UNIQUE,lesson_sha256 TEXT NOT NULL)""")
        known={r[0]:r[1] for r in db.execute("SELECT id,lesson_sha256 FROM curriculum3_lesson")}
        release=db.execute("SELECT material,catalog_sha256 FROM curriculum3_release WHERE pin=?",(pin,)).fetchone()
        files=material_files(pin,lessons)
        if release:
            check(Path(release[0]).resolve()==folder and release[1]==sha(files["candidate-lessons.jsonl"]),"该教材已绑定另一版本的材料目录")
        for item in lessons:
            key=item["id"]
            if key in old:
                check(old[key]["version"]==item["lesson_sha256"] and known.get(key)==item["lesson_sha256"],
                      "现有课程号由其他来源占用，终止本次事务："+key)
            else:check(key not in known,"课程索引存在但学习卡缺失："+key)
        materialize(folder,files)
        db.execute("INSERT OR IGNORE INTO curriculum3_release VALUES(?,?,?,?,?)",
                   (pin,archive_name,str(folder),sha(files["candidate-lessons.jsonl"]),time.time()))
        for x in lessons:
            if x["id"] in old:continue
            at,end=x["lines"]
            location=f"{x['book']}，第 {at}–{end} 行"+(f"；{x['index_id']}" if x["index_id"] else "")
            origin=f"{folder/'candidate-lessons.jsonl'}（{archive_name} SHA256 {pin}）"
            db.execute("""INSERT INTO study3_card(id,title,body,source,locator,version,kind,boundary,target)
                VALUES(?,?,?,?,?,?,'课程课文',?,2)""",(x["id"],x["title"],x["definition"],origin,location,
                x["lesson_sha256"],x["type"]+"。"+x["scope"]+"　这份课文仅含有标签的训练例，未提供独立迁移判卷。"))
            db.execute("INSERT INTO curriculum3_lesson VALUES(?,?,?,?,?,?,?,?)",
                       (x["id"],pin,x["book"],x["book_sha256"],at,end,x["index_id"],x["lesson_sha256"]))
        check(db.execute("SELECT COUNT(*) FROM curriculum3_lesson WHERE package_pin=?",(pin,)).fetchone()[0]==len(lessons),"教材版本登记不完整")
        total=db.execute("SELECT COUNT(*) FROM study3_card").fetchone()[0]
        db.commit();return {**report,"inserted":report["would_insert"],"cards_after":total,"materials":str(folder)}
    except BaseException:
        db.rollback();raise

def main():
    ap=ArgumentParser(description="导入用户提供的完整课本候选素材")
    mode=ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--inspect",action="store_true");mode.add_argument("--apply",action="store_true")
    ap.add_argument("--archive",type=Path,default=ARCHIVE)
    ap.add_argument("--database","--db",type=Path,help="现有再再 3.0 SQLite 库；正式写入时必须显式指定")
    ap.add_argument("--materials",type=Path,default=ROOT/"learning_materials/curriculum")
    args=ap.parse_args();pin,lessons=read_book(args.archive)
    report=json.loads(material_files(pin,lessons)["manifest.json"])
    if args.apply and args.database is None:ap.error("--apply 需要显式指定 --database。")
    if args.database:
        check(args.database.is_file(),"指定数据库不存在")
        mode="rw" if args.apply else "ro"
        with closing(sqlite3.connect(args.database.resolve().as_uri()+"?mode="+mode,uri=True,timeout=45)) as db:
            db.row_factory=sqlite3.Row
            db.execute("PRAGMA synchronous=FULL")
            if args.apply:report.update(apply(db,pin,lessons,(args.materials/pin).resolve(),args.archive.name))
            else:report.update(comparison(db,lessons)[1])
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=="__main__":main()

