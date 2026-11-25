import json
import subprocess
import sys

binary=sys.argv[1]
examples=[
    ('小洛，一加一等于几/', 2, (1,1)),
    ('1+1=？', 2, (1,1)),
    ('二加上三等于多少？', 5, (2,3)),
    ('十六加二十四等于几', 40, (16,24)),
    ('小洛, 零 + 三 等于多少', 3, (0,3)),
    ('42＋九十九＝?', 141, (42,99)),
    ('999999 + 999999 = ?', 1999998, (999999,999999)),
    ('一加一等于三', None, None),
    ('你很可爱', None, None),
    ('半个加一个等于多少', None, None),
    ('三加三再加五是多少', None, None),
    ('一加一等于几/写状态', None, None),
    (':observe x y(z)', None, None),
]
proc=subprocess.run([binary,'--ask-basic-arithmetic'],input=''.join(q+'\n' for q,_,_ in examples),
                    encoding='utf-8', capture_output=True, timeout=15)
assert proc.returncode==0 and not proc.stderr,proc
for (phrase,value,operands),line in zip(examples,proc.stdout.splitlines(),strict=True):
    row=json.loads(line)
    assert row['value']==value and not row['writes_state'], (phrase,row)
    if value is None:
        assert row['status']=='unparsed' and 'proof' not in row,(phrase,row)
    else:
        proof=row['proof']
        assert row['status']=='solved' and proof['status']=='POSITIVE'
        check,=proof['positive']['nodes'][0]['checks']
        assert check['predicate']=='qty_add'
        assert [a['value'] for a in check['arguments']]==[f'{p}@item' for p in (*operands,value)]
print('PASS: 7 original/compositional Chinese or symbolic addition questions, 6 abstentions; unknown result inferred by native qty_add')
