import logging
from bs4 import BeautifulSoup
from urllib.parse import urljoin

logging.basicConfig(level=logging.INFO)


class MHWParser:
    """解析 mhworld.kiranico.com 怪物页面与列表的解析器（基于页面结构的启发式解析）"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def parse_monster_list(self, html_content):
        soup = BeautifulSoup(html_content, 'html.parser')
        results = []

        # 优先匹配你提供的表格结构：<table class="table-padded"> 中的每一行
        rows = soup.select('table.table-padded tbody tr')
        if rows:
            for row in rows:
                try:
                    tds = row.select('td')
                    if not tds:
                        continue

                    # 第一列包含图标和链接
                    first = tds[0]
                    a = first.select_one('a')
                    name = a.get_text(strip=True) if a else first.get_text(strip=True)
                    url = a.get('href') if a and a.get('href') else None
                    img = first.select_one('img')
                    image = img.get('src') if img else ''

                    # 接下来通常为五个元素抗性值（列顺序与页面一致）
                    element_values = {}
                    # 使用列名 element_1..element_5
                    for i in range(1, 6):
                        idx = i  # tds 索引 1..5
                        val = None
                        if idx < len(tds):
                            text = tds[idx].get_text(strip=True)
                            # 可能包含换行或图标，尝试取整数
                            try:
                                val = int(text)
                            except Exception:
                                # 尝试提取数字
                                import re

                                m = re.search(r"(-?\d+)", text)
                                val = int(m.group(1)) if m else None
                        element_values[f'element_{i}'] = val if val is not None else ''

                    results.append({
                        'name': name,
                        'url': url,
                        'image': image,
                        'elements': element_values,
                        'raw': row.decode_contents() if hasattr(row, 'decode_contents') else ''
                    })
                except Exception as e:
                    self.logger.debug(f"解析表格行失败: {e}")

            return results

        # 退化：保持对 .projects-list 的支持（旧实现）
        for box in soup.select('.projects-list .project-box'):
            try:
                img = box.select_one('img')
                image = img.get('src') if img else ''

                name_elem = box.select_one('.project-title .align-self-center') or box.select_one('.project-title')
                name = name_elem.get_text(strip=True) if name_elem else (img.get('alt') if img else '')

                a = box.select_one('a')
                url = a.get('href') if a else None

                desc = ''
                info = box.select_one('.project-info .col-sm-6')
                if info:
                    desc = info.get_text(' ', strip=True)

                results.append({'name': name, 'url': url, 'image': image, 'description': desc})
            except Exception as e:
                self.logger.debug(f"解析列表项失败: {e}")

        # 最后退化为提取链接文本
        if not results:
            for a in soup.select('a')[:200]:
                href = a.get('href')
                text = a.get_text(strip=True)
                if href and text:
                    results.append({'name': text, 'url': href, 'image': '', 'description': ''})

        return results

    def parse_monster_page(self, html_content, base_url=None):
        soup = BeautifulSoup(html_content, 'html.parser')
        data = {
            'name': '',
            'description': '',
            'base_data': {},
            'hitzone_data': [],
            'status_effects': [],
            'materials': []
        }

        # 名称：优先 img alt 或 project title
        img = soup.select_one('.project-title img') or soup.select_one('#content-top-header img')
        if img and img.get('alt'):
            data['name'] = img.get('alt').strip()
        else:
            title = soup.select_one('.project-title .align-self-center') or soup.select_one('h1')
            if title:
                data['name'] = title.get_text(strip=True)

        # 描述：project-info 第一列文本
        pinfo = soup.select_one('.project-info .col-sm-6')
        if pinfo:
            data['description'] = pinfo.get_text(' ', strip=True)
        else:
            # fallback: first paragraph in article
            p = soup.select_one('#mhworld-article p') or soup.select_one('.content-box p')
            if p:
                data['description'] = p.get_text(' ', strip=True)

        # 部位伤害 / 肉质：寻找含有表头 'Part' 或 '切断' 的表格
        tables = soup.select('table')
        for table in tables:
            headers = [th.get_text(strip=True) for th in table.select('thead th')]
            if not headers:
                # 有些表格没有 thead，尝试首行 th 或 td
                first_row = table.select_one('tr')
                if first_row:
                    headers = [c.get_text(strip=True) for c in first_row.select('th,td')]

            header_text = ' '.join(headers).lower()
            if 'part' in header_text or '切断' in header_text or '肉质' in header_text or '耐性' in header_text:
                # 解析为 hitzone 风格表格
                cols = headers if headers else []
                for row in table.select('tr')[1:]:
                    cells = [td.get_text(strip=True) for td in row.select('td')]
                    if not cells:
                        continue
                    entry = {}
                    for i, v in enumerate(cells):
                        key = cols[i] if i < len(cols) and cols[i] else f'col{i}'
                        entry[key] = v
                    data['hitzone_data'].append(entry)
                continue

        # 素材/掉落：查找表格行的第二列包含 % 的表格
        for table in tables:
            rows = table.select('tr')
            if not rows:
                continue
            # 判断是否为素材表（任一行第二列含 % 或 '掉落' 字样）
            is_material = False
            for r in rows:
                tds = r.select('td')
                if len(tds) >= 2 and ('%' in tds[-1].get_text() or '掉落' in tds[-1].get_text() or '剥取' in tds[0].get_text()):
                    is_material = True
                    break
            if not is_material:
                continue

            for r in rows:
                tds = r.select('td')
                if len(tds) >= 2:
                    name = tds[0].get_text(' ', strip=True)
                    rate = tds[-1].get_text(strip=True)
                    # clean name (可能包含链接和图标)
                    if name and rate:
                        data['materials'].append({'name': name, 'rate': rate})

        # base_data: 尝试从 balance-table 中抓取体力等值
        btab = soup.select_one('.balance-table table')
        if btab:
            for tr in btab.select('tr'):
                tds = tr.select('td')
                if len(tds) >= 2:
                    # 有些单元格使用 strong 表示值，后面有 label
                    key = tds[0].get_text(' ', strip=True)
                    val = tds[1].get_text(' ', strip=True)
                    if val:
                        data['base_data'][key or 'val'] = val

        # 补充：添加源 URL
        if base_url:
            data['source_url'] = base_url

        return data
