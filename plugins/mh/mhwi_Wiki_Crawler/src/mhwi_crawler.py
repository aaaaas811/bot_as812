import os
import json
import logging
from pathlib import Path
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from mhwi_parser import MHWParser

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


class MHWICrawler:
    """MH:World (mhworld.kiranico.com) 爬虫入口"""

    def __init__(self, base_url="https://mhworld.kiranico.com/zh/monsters"):
        self.base_url = base_url
        self.session = requests.Session()
        retries = Retry(total=3, backoff_factor=0.6, status_forcelist=(500, 502, 503, 504))
        self.session.mount("https://", HTTPAdapter(max_retries=retries))

        # 保存到 plugins/mh/data/mhwi
        self.data_dir = os.path.join(Path(__file__).resolve().parents[2], 'data', 'mhwi')
        os.makedirs(self.data_dir, exist_ok=True)

    def _request(self, url, timeout=12):
        logging.info(f"请求 URL: {url}")
        r = self.session.get(url, timeout=timeout)
        r.raise_for_status()
        return r

    def get_monster_list(self):
        """获取怪物列表页面并解析出每个怪物的简要信息（name/url,image,description）"""
        try:
            resp = self._request(self.base_url)
            parser = MHWParser()
            return parser.parse_monster_list(resp.text)
        except Exception as e:
            logging.error(f"获取怪物列表失败: {e}")
            return []

    def get_monster_data(self, monster_url):
        try:
            resp = self._request(monster_url)
            parser = MHWParser()
            return parser.parse_monster_page(resp.text, monster_url)
        except Exception as e:
            logging.error(f"获取怪物详情失败 {monster_url}: {e}")
            return None

    def _safe_filename(self, name: str) -> str:
        import re
        name = name.strip() if name else 'unknown'
        name = re.sub(r'[\\/:*?"<>|\s]+', '_', name)
        return name + '.json'

    def save_monster_data(self, monster_data):
        if not monster_data:
            logging.warning("没有怪物数据可保存")
            return
        fname = self._safe_filename(monster_data.get('name') or monster_data.get('id') or 'monster')
        path = os.path.join(self.data_dir, fname)
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(monster_data, f, ensure_ascii=False, indent=2)
            logging.info(f"已保存: {path}")
        except Exception as e:
            logging.error(f"保存失败: {e}")


def main():
    crawler = MHWICrawler()
    lst = crawler.get_monster_list()
    logging.info(f"抓取到 {len(lst)} 个怪物")
    # 保存列表
    try:
        with open(os.path.join(crawler.data_dir, 'monster_list.json'), 'w', encoding='utf-8') as f:
            json.dump(lst, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    # 抓取列表中全部条目
    for idx, m in enumerate(lst):
        url = m.get('url')
        if url and not url.startswith('http'):
            url = 'https://mhworld.kiranico.com' + url
        if not url:
            logging.warning(f"条目缺少 url: {m}")
            continue
        logging.info(f"[{idx+1}/{len(lst)}] 抓取: {m.get('name')} -> {url}")
        data = crawler.get_monster_data(url)
        if data:
            crawler.save_monster_data(data)


if __name__ == '__main__':
    main()
