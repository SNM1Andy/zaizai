# CL 中文候选词典公开资料

两个版本各有 200,000 个固定 sense_id。R001 按原始顺序分成 80 个 JSONL 文件，每个 2,500 行。R002 替换其中 500 条，条件是 ID 和前一版原始义项摘要均匹配。原修订改的是签名、例句等字段；500 条修订均没有更改中文定义。深度审核前均是候选资料。共 60,908 项被机器分为可导入候选，139,092 项待复核，独立人工核准数为 0。

| 字段 | 含义 |
| --- | --- |
| sense_id | 原始语义编号，多义词各有独立编号 |
| upstream_sense_sha256 | 对应原发布记录的摘要，用于定位和版本核对 |
| publication | full 提供完整公开字段。pending_lexical_fields 提供待审词头、读音、词性、释义、CL骨架和原来源。frozen_id_only 和 metadata_only 保留ID、摘要与分组 |
| r002_review、group | R002 治理视图，各项在两种公开版本间可对照；不表示 R001 当时已完成审核 |
| lemma、pinyin、pos、definition | 词头、拼音、词性、候选释义 |
| cl、source_refs | 候选符号骨架、源批或种子编号。CL 字符串在本资料中是数据 |
| boundary、near、ambiguity、examples | 完整公开条目的语义边界、近义、歧义说明与生成的例句 |

1,737 个冻结留出保留编号与摘要，未公开文本。另有 77 项仅公开元数据。待复核词的示例与长说明保留在未公开原件中。完整公开字段有 60,894 条，待审简版字段有 137,292 条。public_stream_sha256 校验公开版的标准 JSONL 序列；original_release_sha256 和原始记录哈希用于溯源，采用不同的输入字节。

下载发布资产后运行以下命令即可复核全部分片，并按需在新文件中生成 R002。只需 Python 3.10 或更新版。

```sh
python verify_lexicon.py cl-lexicon-200k-public-r001-r002.zip --sha256 <公布的ZIP摘要>
python verify_lexicon.py cl-lexicon-200k-public-r001-r002.zip --write-r002 r002.public.jsonl
```

原数据和公开整理版的署名、许可及变更说明见 [ATTRIBUTION.md](ATTRIBUTION.md)。返回的 SHA-256 验证字节和版本对应关系，不能证明每条释义准确。
