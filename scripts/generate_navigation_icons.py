"""Generate a bounded, trusted Lucide subset. No runtime dependency/download.
Usage: python scripts/generate_navigation_icons.py /path/to/lucide-static/package
Source package: lucide-static@1.57.0 (registry.npmjs.org), see license provenance.
"""
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
# key|Chinese label|category|search synonyms (English + Chinese)
METADATA = """
home|首页|general|house 主页 家
settings|设置|general|sliders preferences 偏好 配置
star|收藏|general|favorite 星标
heart|爱心|general|like 喜欢 心愿
search|搜索|general|find 查找 检索
grid|应用格|general|dashboard apps 仪表盘 应用
layers|图层|general|stack 层级 堆叠
box|应用|general|package 容器 软件
compass|指南针|general|explore 发现 导航
flag|旗帜|general|milestone 标记 里程碑
sparkles|灵感|general|magic 灵光 AI 人工智能
archive|归档|general|storage 档案 历史
note|笔记|knowledge|file-text document 文档 记录
book|书籍|knowledge|book-open reading 阅读 图书
folder|文件夹|knowledge|directory 目录 文件
bookmark|书签|knowledge|reading 阅读 标记
library|图书馆|knowledge|books 知识库 藏书
notebook-pen|手写本|knowledge|journal 日记 随笔
notebook-tabs|分类本|knowledge|index 索引 手册
graduation-cap|学习|knowledge|school education 学校 教育 课程
languages|翻译|knowledge|translate language 语言 外语
file-code|代码文档|knowledge|source 源码 脚本
file-spreadsheet|表格文档|knowledge|excel csv 工作表 数据表
file-chart-column|报告|knowledge|report analytics 统计 分析
brain|知识|knowledge|mind 思维 记忆
quote|摘录|knowledge|quotation 引用 语录
server|服务器|technology|host 主机 运维
terminal|终端|technology|shell console 命令行 控制台
code|代码|technology|programming 开发 编程
code-xml|网页代码|technology|html xml markup 前端 标记
database|数据库|technology|sql postgres 数据
cpu|处理器|technology|chip 芯片 硬件
drive|网盘|technology|hard-drive disk nas 硬盘 存储
cloud|云端|technology|cloud 云盘 云服务
monitor|显示器|technology|desktop pc 桌面 电脑
smartphone|手机|technology|mobile android 移动 安卓
network|网络|technology|lan topology 局域网 拓扑
router|路由器|technology|gateway 路由 网关
wifi|无线网络|technology|wlan 无线 热点
git-branch|版本分支|technology|git repository 分支 仓库
bug|调试|technology|debug issue 故障 缺陷
container|容器|technology|docker kubernetes k8s 集群
webhook|自动回调|technology|hook api 接口 自动化
shield-check|安全|technology|security protection 防护 认证
key-round|密钥|technology|password token 密码 凭据
lock-keyhole|隐私|technology|lock private 加密 锁
fingerprint|身份|technology|identity authentication 指纹 验证
globe|网站|communication|web internet 浏览器 互联网
link|链接|communication|url 地址 超链接
external-link|外部链接|communication|open 跳转 外站
mail|邮件|communication|email inbox 邮箱 信件
messages-square|聊天|communication|chat message 消息 会话
contact|通讯录|communication|address contact 联系人
users|团队|communication|team people 成员 协作
video|视频通话|communication|call meeting 视频会议
rss|订阅|communication|feed news 新闻 信息流
send|发送|communication|share 邮寄 投递
radio|广播|communication|broadcast 播客 电台
megaphone|公告|communication|announcement 通知 宣传
image|图片|media|photo gallery 照片 图库 相册
camera|相机|media|photography 拍照 摄影
film|电影|media|movie cinema 影视 放映
clapperboard|剪辑|media|video editing 视频 制作
music|音乐|media|song audio 歌曲 音频
headphones|耳机|media|listen 聆听 收听
mic|麦克风|media|voice recording 语音 录音
palette|调色盘|media|art color 艺术 绘画
paintbrush|画笔|media|design drawing 设计 创作
aperture|光圈|media|lens 镜头 摄影
podcast|播客|media|audio talk 节目 声音
tv|电视|media|stream media 流媒体 追剧
calendar|日历|productivity|schedule agenda 日程 排期
clipboard-list|清单|productivity|checklist todo 待办 任务
list-checks|任务完成|productivity|done tasks 检查 勾选
kanban|看板|productivity|board workflow 项目 工作流
briefcase-business|工作|productivity|career job 职业 招聘
notepad-text|备忘|productivity|memo reminder 便笺 提醒
clock|时钟|productivity|time 时间 历史
timer|计时器|productivity|countdown pomodoro 倒计时 番茄钟
alarm-clock|闹钟|productivity|wake reminder 起床 提醒
bell|通知|productivity|notification alert 消息 提醒
chart-no-axes-combined|趋势|productivity|chart statistics 统计 图表 趋势
presentation|演示|productivity|slides ppt 幻灯片 汇报
target|目标|productivity|goal focus 专注 计划
calculator|计算器|productivity|math calculation 数学 计算
workflow|工作流|productivity|automation pipeline 流程 自动化
wallet|钱包|life|money budget 预算 资金
credit-card|银行卡|life|payment 支付 账单
receipt|收据|life|invoice expense 发票 记账
shopping-cart|购物车|life|shop mall 购物 商城
utensils|餐饮|life|food restaurant 美食 餐厅
coffee|咖啡|life|drink break 饮品 休息
cooking-pot|烹饪|life|recipe kitchen 菜谱 厨房
house-plug|智能家居|life|smart home 家电 智能
heart-pulse|健康|life|health medical 医疗 心率
activity|监测|life|pulse monitor 状态 活动
pill|药品|life|medicine medication 用药 医药
dumbbell|健身|life|fitness exercise 运动 锻炼
bike|骑行|life|cycling bicycle 自行车 运动
paw-print|宠物|life|pet cat dog 猫 狗
leaf|植物|life|plant nature 自然 园艺
sprout|成长|life|growth seed 发芽 成长
map|地图|travel|atlas geography 地理 位置
map-pin|地点|travel|location place 定位 地址
plane|旅行|travel|flight airplane 航班 飞机
train-front|火车|travel|railway train 铁路 高铁
car|汽车|travel|vehicle driving 车辆 驾驶
luggage|行李|travel|trip suitcase 出行 箱包
mountain|山峰|travel|hiking outdoors 徒步 户外
tent|露营|travel|camping camp 营地 帐篷
sun|晴天|travel|weather daylight 天气 日光
moon|夜晚|travel|night sleep 睡眠 月亮
cloud-rain|雨天|travel|rain weather 天气 下雨
gamepad-2|游戏|interests|game gaming 手柄 娱乐
dices|桌游|interests|dice boardgame 骰子 桌面游戏
puzzle|拼图|interests|puzzle hobby 益智 爱好
trophy|奖杯|interests|achievement award 成就 奖项
medal|勋章|interests|honor reward 荣誉 奖励
rocket|探索|interests|launch space 太空 发射
flask-conical|实验|interests|science chemistry 科学 化学
microscope|研究|interests|biology research 生物 科研
telescope|天文|interests|astronomy stars 星空 观测
""".strip()
CATEGORIES = dict(general='常用', knowledge='文档知识', technology='开发网络', communication='沟通网站', media='媒体创作', productivity='工作效率', life='生活健康', travel='出行天气', interests='兴趣探索')
ALIASES = {'file-text': 'note', 'hard-drive': 'drive'}
SOURCE_NAMES = {'note': 'file-text', 'book': 'book-open', 'drive': 'hard-drive', 'grid': 'panels-top-left', 'settings': 'sliders-vertical', 'home': 'house'}
ALLOWED = {'path': {'d'}, 'circle': {'cx','cy','r'}, 'rect': {'x','y','width','height','rx','ry'}, 'line': {'x1','x2','y1','y2'}, 'polyline': {'points'}, 'polygon': {'points'}, 'ellipse': {'cx','cy','rx','ry'}}

def generate(source):
    package = json.loads((source / 'package.json').read_text())
    assert package['version'] == '1.57.0'
    entries = []
    for row in METADATA.splitlines():
        key, label, category, keywords = row.split('|')
        svg = ET.parse(source / 'icons' / (SOURCE_NAMES.get(key, key) + '.svg')).getroot()
        nodes = []
        for child in svg:
            tag = child.tag.split('}')[-1]
            assert tag in ALLOWED and set(child.attrib) <= ALLOWED[tag] | {'fill'}, (key, tag, child.attrib)
            assert child.attrib.get('fill', 'none') in {'none', 'currentColor'}
            nodes.append([tag, child.attrib])
        assert nodes
        entries.append(dict(key=key, label=label, category=category, keywords=keywords, nodes=nodes))
    dest = ROOT / 'frontend/src/icons'
    dest.mkdir(exist_ok=True)
    (dest / 'navigation-icons.json').write_text(json.dumps(dict(categories=CATEGORIES, aliases=ALIASES, icons=entries), ensure_ascii=False, separators=(',', ':')) + '\n')
    license_dir = ROOT / 'frontend/public/licenses'
    license_dir.mkdir(exist_ok=True, parents=True)
    (license_dir / 'lucide-1.57.0.txt').write_text((source / 'LICENSE').read_text())
    keys = sorted([e['key'] for e in entries] + list(ALIASES))
    (ROOT / 'app/navigation_icons.py').write_text('"""Generated by scripts/generate_navigation_icons.py; parity tested against the UI catalog."""\nNAVIGATION_ICONS = frozenset(' + repr(tuple(keys)) + ')\n')
    print(f'{len(entries)} selectable, {len(ALIASES)} compatibility aliases, {len(keys)} legal keys')

if __name__ == '__main__':
    generate(Path(sys.argv[1]))
