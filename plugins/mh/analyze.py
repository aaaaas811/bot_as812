import json
import os


class MonsterAnalyzer:
    """支持多个数据源（例如 data/mhws 和 data/mhwi）的分析器。
    方法支持传入 source 参数来选择数据源；若未提供则在所有源中查找并使用第一个匹配项。"""

    def __init__(self, data_dir):
        base = os.path.join(data_dir, 'data')
        self.base_data_dir = base
        self.sources = []  # 可用数据源目录名
        self.monster_list = []
        self.meat_data = {}  # { source: { name: [...parts...] } }

        # 探测子目录作为各数据源
        try:
            for name in os.listdir(self.base_data_dir):
                path = os.path.join(self.base_data_dir, name)
                if os.path.isdir(path):
                    self.sources.append(name)
            # 加载每个源的 monster_list.json 和肉质数据
            for src in self.sources:
                src_dir = os.path.join(self.base_data_dir, src)
                lst = self._load_monster_list_for(src_dir)
                # 将来源信息注入到条目中，便于展示
                for it in lst:
                    if isinstance(it, dict):
                        it.setdefault('source', src)
                    self.monster_list.append(it)

                self.meat_data[src] = self._load_meat_data_for(src_dir)
        except Exception:
            # 兼容老结构：直接在 data 下寻找文件
            self.sources = []
            self.monster_list = self._load_monster_list_fallback(data_dir)
            self.meat_data = {'default': self._load_meat_data_fallback(data_dir)}

    def _load_monster_list_for(self, src_dir):
        list_path = os.path.join(src_dir, 'monster_list.json')
        try:
            with open(list_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return []

    def _load_meat_data_for(self, src_dir):
        meat_data = {}
        try:
            for fname in os.listdir(src_dir):
                if fname.endswith('.json') and fname != 'monster_list.json':
                    with open(os.path.join(src_dir, fname), 'r', encoding='utf-8') as f:
                        monster = json.load(f)
                        data = monster.get('hitzone_data', [])
                        # 如果是 mhwi 数据源，进行归一化以兼容旧分析逻辑
                        if os.path.basename(src_dir).lower() == 'mhwi':
                            data = [self._normalize_mhwi_entry(e) for e in data]
                        meat_data[monster.get('name', '')] = data
        except Exception:
            pass
        return meat_data

    def _normalize_mhwi_entry(self, entry):
        """将 mhwi 格式的单条部位数据转换为兼容旧逻辑的字段。

        转换规则（基于用户提供的映射说明）：
        - Part -> 部位（去掉括号内的状态）
        - 括号内内容 -> 列1（状态）
        - 切断 -> 斩 / 列2
        - 打击 -> 打 / 列3
        - 遥远 -> 弹 / 列4
        - col4 -> 火 / 列5
        - col5 -> 水 / 列6
        - col6 -> 雷 / 列7
        - col7 -> 冰 / 列8
        - col8 -> 龙 / 列9
        - col9 -> 晕 / 列10
        其余字段原样保留（如 耐力）。
        """
        out = {}
        # 处理 Part 与状态
        part = entry.get('Part', '')
        status = ''
        if part and '(' in part and ')' in part:
            try:
                name = part[:part.rfind('(')].strip()
                status = part[part.rfind('(')+1:part.rfind(')')].strip()
            except Exception:
                name = part
        else:
            name = part
        out['部位'] = name
        out['列1'] = status

        def _num(v):
            try:
                if v is None:
                    return ''
                s = str(v).strip()
                return s
            except:
                return ''

        # 数值映射
        mapping = [
            ('切断', '斩', '列2'),
            ('打击', '打', '列3'),
            ('遥远', '弹', '列4'),
            ('col4', '火', '列5'),
            ('col5', '水', '列6'),
            ('col6', '雷', '列7'),
            ('col7', '冰', '列8'),
            ('col8', '龙', '列9'),
            ('col9', '晕', '列10')
        ]
        for src_key, chi_key, col_key in mapping:
            val = entry.get(src_key)
            v = _num(val)
            out[chi_key] = v
            out[col_key] = v

        # 复制其他可能的字段
        for k, v in entry.items():
            if k in ('Part', '切断', '打击', '遥远', 'col4', 'col5', 'col6', 'col7', 'col8', 'col9'):
                continue
            out[k] = v

        return out

    # 兼容性后备（当没有子目录时）
    def _load_monster_list_fallback(self, data_dir):
        list_path = os.path.join(data_dir, 'data', 'monster_list.json')
        try:
            with open(list_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return []

    def _load_meat_data_fallback(self, data_dir):
        meat_data = {}
        base = os.path.join(data_dir, 'data')
        try:
            for fname in os.listdir(base):
                if fname.endswith('.json') and fname != 'monster_list.json':
                    with open(os.path.join(base, fname), 'r', encoding='utf-8') as f:
                        monster = json.load(f)
                        meat_data[monster.get('name', '')] = monster.get('hitzone_data', [])
        except Exception:
            pass
        return meat_data

    def get_monster_intro(self, monster_name):
        # 查找怪物信息（在已加载的 monster_list 中查找）
        monster_info = None
        for m in self.monster_list:
            if m.get('name') == monster_name:
                monster_info = m
                break
        if not monster_info:
            return "未找到该怪物信息"

        # 查找对应源下的 json 文件（优先使用 monster_info 中的 source）
        base_data = None
        src = monster_info.get('source')
        if src:
            json_path = os.path.join(self.base_data_dir, src, f"{monster_name}.json")
            if os.path.exists(json_path):
                try:
                    with open(json_path, 'r', encoding='utf-8') as f:
                        monster_json = json.load(f)
                        base_data = monster_json.get('base_data', {})
                except Exception:
                    base_data = None

        # 组装输出
        lines = [f"图片: {monster_info.get('image','')}",
                 f"名称: {monster_info.get('name','')}",
                 f"简介: {monster_info.get('description','')}"]
        if base_data:
            key_map = {
                "Species": "怪物种类",
                "BaseHealth": "基础血量",
                "HunterRankPoint": "调查点数"
            }
            lines.append("基础数据:")
            for k in ["Species", "BaseHealth", "HunterRankPoint"]:
                v = base_data.get(k, "")
                if v != "":
                    lines.append(f"{key_map.get(k, k)}：{v}")
        # 添加弱点/肉质查询提示（指示不同数据源命令）
        lines.append(f"输入/ws肉质 {monster_name} 或 /wi肉质 {monster_name} 查看不同数据源的肉质表\n输入/ws弱点 {monster_name} 或 /wi弱点 {monster_name} 查看弱点简析")
        return "\n".join(lines)

    def get_monster_weakness(self, monster_name, source=None):
        # 若指定 source，则从指定的源读取；否则在所有源中查找第一个匹配
        data = None
        if source:
            data = self.meat_data.get(source, {}).get(monster_name)
        else:
            for s, table in self.meat_data.items():
                if monster_name in table:
                    data = table.get(monster_name)
                    break

        if not data:
            return "未找到该怪物的肉质数据"

        parts = []
        for part in data:
            part_name = part.get("部位", "")
            modifier = part.get("列1", "")
            if not modifier:
                modifier = "正常"
            values = [
                part.get("斩", part.get("列2", "")),
                part.get("打", part.get("列3", "")),
                part.get("弹", part.get("列4", "")),
                part.get("火", part.get("列5", "")),
                part.get("水", part.get("列6", "")),
                part.get("雷", part.get("列7", "")),
                part.get("冰", part.get("列8", "")),
                part.get("龙", part.get("列9", "")),
                part.get("晕", part.get("列10", ""))
            ]
            try:
                parts.append({
                    "部位": part_name,
                    "状态": modifier,
                    "斩": float(values[0]) if str(values[0]).replace('.','',1).isdigit() else -999,
                    "打": float(values[1]) if str(values[1]).replace('.','',1).isdigit() else -999,
                    "弹": float(values[2]) if str(values[2]).replace('.','',1).isdigit() else -999,
                    "火": float(values[3]) if str(values[3]).replace('.','',1).isdigit() else -999,
                    "水": float(values[4]) if str(values[4]).replace('.','',1).isdigit() else -999,
                    "雷": float(values[5]) if str(values[5]).replace('.','',1).isdigit() else -999,
                    "冰": float(values[6]) if str(values[6]).replace('.','',1).isdigit() else -999,
                    "龙": float(values[7]) if str(values[7]).replace('.','',1).isdigit() else -999
                })
            except:
                pass

        # 按状态分组，排除 '伤口' 和 '弱点'
        state_map = {}
        for p in parts:
            st = p.get('状态', '正常')
            if st in ['伤口', '弱点']:
                continue
            state_map.setdefault(st, []).append(p)

        if not state_map:
            return f"{monster_name}：\n未找到可用于分组的状态（或仅含 伤口/弱点）"

        # 生成分析（仅输出简析块）
        analysis_state = '正常' if '正常' in state_map else (next(iter(state_map.keys())) if state_map else None)
        g = state_map[analysis_state]
        def _build_top_two(key):
            left_map = {}
            right_map = {}
            others = {}
            for p in g:
                name = p.get('部位','')
                val = p.get(key, -999)
                if val == -999:
                    continue
                if name.startswith('左') and len(name) > 1:
                    suf = name[1:]
                    left_map[suf] = int(val)
                elif name.startswith('右') and len(name) > 1:
                    suf = name[1:]
                    right_map[suf] = int(val)
                else:
                    others[name] = int(val)
            entries = []
            all_sufs = sorted(set(list(left_map.keys()) + list(right_map.keys())))
            for suf in all_sufs:
                l = left_map.get(suf)
                r = right_map.get(suf)
                if l is not None and r is not None:
                    if l == r:
                        entries.append((f"左(右){suf}", l))
                    else:
                        entries.append((f"左{suf}", l))
                        entries.append((f"右{suf}", r))
                else:
                    if l is not None:
                        entries.append((f"左{suf}", l))
                    if r is not None:
                        entries.append((f"右{suf}", r))
            for n, v in others.items():
                entries.append((n, v))
            entries_sorted = sorted(entries, key=lambda x: x[1], reverse=True)
            return [f"{e[0]}:{e[1]}" for e in entries_sorted[:2]]

        phys_1 = _build_top_two('斩')
        phys_2 = _build_top_two('打')
        phys_3 = _build_top_two('弹')
        lines = []
        lines.append('====简析(正常状态)====')
        # 斩
        if phys_1:
            lines.append(f"🔺物理: 斩🔪 {phys_1[0]}")
            if len(phys_1) > 1:
                lines.append(f"{' ' * 24}{phys_1[1]}")
        else:
            lines.append(f"🔺物理: 斩🔪 无")
        # 打
        if phys_2:
            lines.append(f"{' ' * 13}打🔨 {phys_2[0]}")
            if len(phys_2) > 1:
                lines.append(f"{' ' * 23}{phys_2[1]}")
        else:
            lines.append(f"{' ' * 13}打🔨 无")
        # 弹
        if phys_3:
            lines.append(f"{' ' * 13}弹🔫 {phys_3[0]}")
            if len(phys_3) > 1:
                lines.append(f"{' ' * 23}{phys_3[1]}")
        else:
            lines.append(f"{' ' * 13}弹🔫 无")

        # 五属性摘要
        attr_keys = ['火', '水', '雷', '冰', '龙']
        attr_avgs = {}
        for k in attr_keys:
            vals = [p[k] for p in parts if p[k] != -999]
            if vals:
                attr_avgs[k] = sum(vals)/len(vals)
        if attr_avgs:
            best_attr = max(attr_avgs.items(), key=lambda x: x[1])
            worst_attr = min(attr_avgs.items(), key=lambda x: x[1])
            emoji_map = {'火':'🔥','水':'💧','雷':'⚡️','冰':'🧊','龙':'🐉'}
            best_emo = emoji_map.get(best_attr[0], best_attr[0])
            worst_emo = emoji_map.get(worst_attr[0], worst_attr[0])
            lines.append(f"🔺最佳属性:{best_emo}({best_attr[1]:.1f})")
            lines.append(f"🔻最差属性:{worst_emo}({worst_attr[1]:.1f})")

        return f"{monster_name}：\n" + "\n".join(lines)

    def get_monster_meat(self, monster_name, source=None):
        # 同上，支持 source 指定
        data = None
        if source:
            data = self.meat_data.get(source, {}).get(monster_name)
        else:
            for s, table in self.meat_data.items():
                if monster_name in table:
                    data = table.get(monster_name)
                    break

        if not data:
            return "未找到该怪物的肉质数据"

        parts = []
        header = "从左到右依次为：\n部位 斩 打 弹 火 水 雷 冰 龙"
        lines = [header]
        for part in data:
            part_name = part.get("部位", "")
            modifier = part.get("列1", "")
            if not modifier:
                modifier = "正常"
            values = [
                part.get("斩", part.get("列2", "")),
                part.get("打", part.get("列3", "")),
                part.get("弹", part.get("列4", "")),
                part.get("火", part.get("列5", "")),
                part.get("水", part.get("列6", "")),
                part.get("雷", part.get("列7", "")),
                part.get("冰", part.get("列8", "")),
                part.get("龙", part.get("列9", "")),
                part.get("晕", part.get("列10", ""))
            ]
            try:
                parts.append({
                    "部位": part_name,
                    "状态": modifier,
                    "斩": float(values[0]) if str(values[0]).replace('.','',1).isdigit() else -999,
                    "打": float(values[1]) if str(values[1]).replace('.','',1).isdigit() else -999,
                    "弹": float(values[2]) if str(values[2]).replace('.','',1).isdigit() else -999,
                    "火": float(values[3]) if str(values[3]).replace('.','',1).isdigit() else -999,
                    "水": float(values[4]) if str(values[4]).replace('.','',1).isdigit() else -999,
                    "雷": float(values[5]) if str(values[5]).replace('.','',1).isdigit() else -999,
                    "冰": float(values[6]) if str(values[6]).replace('.','',1).isdigit() else -999,
                    "龙": float(values[7]) if str(values[7]).replace('.','',1).isdigit() else -999
                })
            except:
                pass

        # 按状态分组，排除 '伤口' 和 '弱点'
        state_map = {}
        for p in parts:
            st = p.get('状态', '正常')
            if st in ['伤口', '弱点']:
                continue
            state_map.setdefault(st, []).append(p)

        if not state_map:
            lines.append('未找到可用于分组的状态（或仅含 伤口/弱点）')
        else:
            for st in sorted(state_map.keys()):
                lines.append(f'=== 状态: {st} ===')
                group = state_map[st]
                for g in group:
                    vals = [g.get(k, -999) for k in ['斩', '打', '弹', '火', '水', '雷', '冰', '龙']]
                    # 如果这一行所有值均为 -999（即无有效数值），则跳过（避免输出全 '-' 的占位行）
                    if all(v == -999 for v in vals):
                        continue
                    vals_str = ' '.join(str(int(v)) if v != -999 else '-' for v in vals)
                    lines.append(f"{g['部位']} {vals_str}")

        # 生成简析
        analysis_state = '正常' if '正常' in state_map else (next(iter(state_map.keys())) if state_map else None)
        if analysis_state:
            g = state_map[analysis_state]
            def _build_top_two(key):
                left_map = {}
                right_map = {}
                others = {}
                for p in g:
                    name = p.get('部位','')
                    val = p.get(key, -999)
                    if val == -999:
                        continue
                    if name.startswith('左') and len(name) > 1:
                        suf = name[1:]
                        left_map[suf] = int(val)
                    elif name.startswith('右') and len(name) > 1:
                        suf = name[1:]
                        right_map[suf] = int(val)
                    else:
                        others[name] = int(val)
                entries = []
                all_sufs = sorted(set(list(left_map.keys()) + list(right_map.keys())))
                for suf in all_sufs:
                    l = left_map.get(suf)
                    r = right_map.get(suf)
                    if l is not None and r is not None:
                        if l == r:
                            entries.append((f"左(右){suf}", l))
                        else:
                            entries.append((f"左{suf}", l))
                            entries.append((f"右{suf}", r))
                    else:
                        if l is not None:
                            entries.append((f"左{suf}", l))
                        if r is not None:
                            entries.append((f"右{suf}", r))
                for n, v in others.items():
                    entries.append((n, v))
                entries_sorted = sorted(entries, key=lambda x: x[1], reverse=True)
                return [f"{e[0]}:{e[1]}" for e in entries_sorted[:2]]

            phys_1 = _build_top_two('斩')
            phys_2 = _build_top_two('打')
            phys_3 = _build_top_two('弹')
            lines.append('====简析(正常状态)====')
            # 斩
            if phys_1:
                lines.append(f"🔺物理: 斩🔪 {phys_1[0]}")
                if len(phys_1) > 1:
                    lines.append(f"{' ' * 24}{phys_1[1]}")
            else:
                lines.append(f"🔺物理: 斩🔪 无")
            # 打
            if phys_2:
                lines.append(f"{' ' * 13}打🔨 {phys_2[0]}")
                if len(phys_2) > 1:
                    lines.append(f"{' ' * 23}{phys_2[1]}")
            else:
                lines.append(f"{' ' * 13}打🔨 无")
            # 弹
            if phys_3:
                lines.append(f"{' ' * 13}弹🔫 {phys_3[0]}")
                if len(phys_3) > 1:
                    lines.append(f"{' ' * 23}{phys_3[1]}")
            else:
                lines.append(f"{' ' * 13}弹🔫 无")

        attr_keys = ['火', '水', '雷', '冰', '龙']
        attr_avgs = {}
        for k in attr_keys:
            vals = [p[k] for p in parts if p[k] != -999]
            if vals:
                attr_avgs[k] = sum(vals)/len(vals)
        if attr_avgs:
            best_attr = max(attr_avgs.items(), key=lambda x: x[1])
            worst_attr = min(attr_avgs.items(), key=lambda x: x[1])
            emoji_map = {'火':'🔥','水':'💧','雷':'⚡️','冰':'🧊','龙':'🐉'}
            best_emo = emoji_map.get(best_attr[0], best_attr[0])
            worst_emo = emoji_map.get(worst_attr[0], worst_attr[0])
            lines.append(f"🔺最佳属性:{best_emo}({best_attr[1]:.1f})")
            lines.append(f"🔻最差属性:{worst_emo}({worst_attr[1]:.1f})")

        return f"{monster_name}：\n" + "\n".join(lines)