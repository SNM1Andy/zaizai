# 数据来源与许可

## CC-CEDICT

- 项目：CC-CEDICT（https://cc-cedict.org/）
- 许可：Creative Commons Attribution-ShareAlike 3.0 Unported（CC BY-SA 3.0）
- 用途：词头、拼音、英文义项作为生成种子。
- 要求：再分发时保留署名，并以相同方式共享衍生数据。本包中的词头与英文义项来自 CC-CEDICT；中文定义与例句为生成内容，按 CC BY-SA 3.0 共享。

## jieba

- 项目：jieba（https://github.com/fxsjy/jieba）
- 许可：MIT
- 用途：词频与补充词头。

## 本地模型

- 权重：Qwen3.5-9B-Q4_K_M.gguf，本地推理，未随包分发。
- 生成内容：中文定义、边界、近义、歧义说明、例句、CL 骨架。
- 模型权重适用其自身许可；本包只包含生成文本，不包含权重。

## 本包

- `lexicon-200k.jsonl` 等衍生数据按 CC BY-SA 3.0 共享，保留上述署名。
- 未并入任何正式词典。
