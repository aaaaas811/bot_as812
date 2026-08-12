"""MHRise (Sunbreak) 怪物页面解析器。

数据源: https://mhrise.kiranico.com/zh
页面为服务端渲染的 HTML（Alpine.js 仅用于表格筛选，数据本身在 DOM 中）。

输出数据格式与 analyze.py 兼容（对齐 mhwi 归一化格式）：
    monster_list.json: [{name, url, image}]
    每怪物 JSON: {name, description, image, base_data, hitzone_data: [{部位, 列1, 斩, 打, 弹, 火, 水, 雷, 冰, 龙, 列10}]}
"""
import logging
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO)


class MHRSParser:
    """解析 mhrise.kiranico.com 的怪物列表页与详情页"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    # ---- 怪物列表页 ----

    def parse_monster_list(self, html_content):
        """解析怪物列表页，返回 [{name, url, image}]。

        列表页卡片结构：
            <div class="group relative p-4 ...">
                <img src=".../icons/em082_02.png" alt="怪物名">
                <h3><a href=".../monsters/1061157944">怪物名</a></h3>
        """
        soup = BeautifulSoup(html_content, 'html.parser')
        results = []

        for card in soup.select('div.group.relative'):
            a = card.select_one('h3 a[href*="/zh/data/monsters/"]')
            if not a:
                continue
            name = a.get_text(strip=True)
            url = a.get('href', '')
            img = card.select_one('img')
            image = img.get('src', '') if img else ''
            # 图标使用 https 前缀（页面里是 http://cdn.kiranico.net）
            if image.startswith('http://'):
                image = 'https://' + image[len('http://'):]
            if name:
                results.append({'name': name, 'url': url, 'image': image})

        if not results:
            self.logger.warning("怪物列表解析为空，请检查页面结构是否变化")
        return results

    # ---- 怪物详情页 ----

    def parse_monster_page(self, html_content, fallback_image=""):
        """解析怪物详情页，返回怪物数据字典。

        详情页结构：
            <h1>怪物名</h1>
            <p>简介</p>
            肉质表（列头为图标 hit_slash/hit_strike/hit_shell/element_*）：
                <th>部位</th> <th>State</th> <th>斩</th> <th>打</th> <th>弹</th> <th>火</th> <th>水</th> <th>雷</th> <th>冰</th> <th>龙</th> <th>晕</th>
        """
        soup = BeautifulSoup(html_content, 'html.parser')
        monster = {
            'name': '',
            'description': '',
            'image': fallback_image,
            'base_data': {},
            'hitzone_data': [],
        }

        # 名称
        h1 = soup.select_one('h1')
        if h1:
            monster['name'] = h1.get_text(strip=True)

        # 简介（h1 之后的第一个 p）
        if h1:
            p = h1.find_next('p')
            if p:
                monster['description'] = p.get_text(strip=True)

        # 肉质表：定位包含 hit_slash 图标（斩击列特征）的表格
        hitzone_table = None
        for table in soup.select('table'):
            if table.select_one('img[src*="hit_slash"]'):
                hitzone_table = table
                break

        if hitzone_table is None:
            self.logger.warning(f"未找到肉质表: {monster['name']}")
            return monster

        for row in hitzone_table.select('tbody tr'):
            cells = row.select('td')
            if len(cells) < 10:
                continue
            part_name = cells[0].get_text(strip=True)
            if not part_name:
                continue

            # State 数字 → 状态名（0 为正常，其余按"状态N"展示）
            state_raw = cells[1].get_text(strip=True)
            state = '正常' if state_raw in ('', '0') else f'状态{state_raw}'

            values = [c.get_text(strip=True) for c in cells[2:11]]
            # 列顺序: 斩 打 弹 火 水 雷 冰 龙 晕
            keys = ['斩', '打', '弹', '火', '水', '雷', '冰', '龙', '晕']
            entry = {'部位': part_name, '列1': state}
            for key, val in zip(keys, values):
                entry[key] = val
            monster['hitzone_data'].append(entry)

        if not monster['hitzone_data']:
            self.logger.warning(f"肉质表无有效行: {monster['name']}")

        return monster
