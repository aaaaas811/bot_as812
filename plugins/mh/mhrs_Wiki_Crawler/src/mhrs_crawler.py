"""MHRise (Sunbreak) 数据爬虫。

数据源: https://mhrise.kiranico.com/zh
数据输出: plugins/mh/data/mhrs/（monster_list.json + 每怪物一个 JSON）
"""
import json
import os
import logging
from mhrs_parser import MHRSParser
from http_utils import HttpUtils

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)


class MHRSCrawler:
    """怪物猎人崛起：曙光 数据爬虫"""

    def __init__(self, base_url="https://mhrise.kiranico.com/zh/data/monsters?view=lg"):
        """初始化爬虫

        Args:
            base_url: 怪物列表页 URL（lg 视图包含全部怪物卡片）
        """
        self.base_url = base_url
        self.http_utils = HttpUtils(retry_times=3, retry_interval=2, timeout=15)

        # 数据目录：plugins/mh/data/mhrs
        self.data_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            'data', 'mhrs'
        )
        os.makedirs(self.data_dir, exist_ok=True)

    def _request(self, url):
        """发送 HTTP 请求（带重试）。"""
        try:
            return self.http_utils.get(url)
        except Exception as e:
            logging.error(f"请求失败: {e}")
            raise

    def get_monster_list(self):
        """获取怪物列表 [{name, url, image}]。"""
        logging.info("正在获取怪物列表")
        try:
            response = self._request(self.base_url)
            return MHRSParser().parse_monster_list(response.text)
        except Exception as e:
            logging.error(f"获取怪物列表失败: {e}")
            return []

    def get_monster_data(self, monster_url, fallback_image=""):
        """获取单个怪物详情数据。"""
        logging.info(f"正在获取怪物数据: {monster_url}")
        try:
            response = self._request(monster_url)
            return MHRSParser().parse_monster_page(response.text, fallback_image)
        except Exception as e:
            logging.error(f"获取怪物数据失败: {e}")
            return None

    def save_monster_data(self, monster_data, filename=None):
        """保存怪物数据到 JSON 文件。"""
        if not monster_data:
            logging.warning("没有数据可保存")
            return
        if not filename:
            filename = f"{monster_data.get('name') or 'unknown_monster'}.json"
        file_path = os.path.join(self.data_dir, filename)
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(monster_data, f, ensure_ascii=False, indent=2)
            logging.info(f"数据已保存到: {file_path}")
        except Exception as e:
            logging.error(f"保存数据失败: {e}")


def main():
    """爬取全部怪物数据。"""
    crawler = MHRSCrawler()

    monster_list = crawler.get_monster_list()
    logging.info(f"获取到 {len(monster_list)} 个怪物信息")
    if not monster_list:
        logging.error("怪物列表为空，终止爬取")
        return

    # 保存怪物列表
    with open(os.path.join(crawler.data_dir, 'monster_list.json'), 'w', encoding='utf-8') as f:
        json.dump(monster_list, f, ensure_ascii=False, indent=2)
    logging.info("怪物列表数据已保存")

    # 爬取每个怪物的详细数据
    ok_count = 0
    for monster in monster_list:
        logging.info(f"正在爬取 {monster['name']} 的数据")
        data = crawler.get_monster_data(monster['url'], monster.get('image', ''))
        if data and data.get('name'):
            # 以中文名保存（与 mhwi/mhws 数据一致），确保文件名安全
            safe_name = data['name'].replace('/', '_').replace('\\', '_').strip()
            crawler.save_monster_data(data, f"{safe_name}.json")
            ok_count += 1

    logging.info(f"爬取完成：成功 {ok_count}/{len(monster_list)}")
    logging.info(f"数据已保存到 {crawler.data_dir}")


if __name__ == "__main__":
    main()
