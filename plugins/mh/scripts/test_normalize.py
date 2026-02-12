import json
import os
from plugins.mh.analyze import MonsterAnalyzer

base = os.path.dirname(os.path.dirname(__file__))  # plugins/mh
ma = MonsterAnalyzer(base)

p = os.path.join(base, 'data', 'mhwi', '冥赤龙.json')
print('测试文件路径:', p)
if os.path.exists(p):
    with open(p, 'r', encoding='utf-8') as f:
        mj = json.load(f)
    entry = mj.get('hitzone_data', [])[0]
    norm = ma._normalize_mhwi_entry(entry)
    print('归一化结果:')
    print(json.dumps(norm, ensure_ascii=False, indent=2))
else:
    print('未找到示例文件')
