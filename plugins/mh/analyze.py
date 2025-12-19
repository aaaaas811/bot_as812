import json
import os

class MonsterAnalyzer:
    def __init__(self, data_dir):
        self.data_dir = os.path.join(data_dir, 'data')
        self.monster_list = self._load_monster_list()
        self.meat_data = self._load_meat_data()

    def _load_monster_list(self):
        list_path = os.path.join(self.data_dir, 'monster_list.json')
        try:
            with open(list_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"怪物列表加载失败: {e}")
            return []

    def _load_meat_data(self):
        meat_data = {}
        for fname in os.listdir(self.data_dir):
            if fname.endswith('.json') and fname != 'monster_list.json':
                with open(os.path.join(self.data_dir, fname), 'r', encoding='utf-8') as f:
                    monster = json.load(f)
                    meat_data[monster['name']] = monster.get('hitzone_data', [])
        return meat_data

    def get_monster_intro(self, monster_name):
        # 查找怪物信息
        monster_info = None
        for m in self.monster_list:
            if m.get('name') == monster_name:
                monster_info = m
                break
        if not monster_info:
            return "未找到该怪物信息"

        # 查找base_data
        json_path = os.path.join(self.data_dir, f'{monster_name}.json')
        base_data = None
        if os.path.exists(json_path):
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    monster_json = json.load(f)
                    base_data = monster_json.get('base_data', {})
            except Exception as e:
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
        # 添加弱点查询提示
        lines.append(f"输入/肉质 {monster_name}查看相应肉质表\n输入/弱点 {monster_name}查看弱点简析")
        return "\n".join(lines)

    def get_monster_weakness(self, monster_name):
        if monster_name not in self.meat_data:
            return "未找到该怪物的肉质数据"

        parts = []
        for part in self.meat_data[monster_name]:
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

    def get_monster_meat(self, monster_name):
        if monster_name not in self.meat_data:
            return "未找到该怪物的肉质数据"

        parts = []
        header = "从左到右依次为：\n部位 斩 打 弹 火 水 雷 冰 龙"
        lines = [header]
        for part in self.meat_data[monster_name]:
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