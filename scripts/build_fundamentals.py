#!/usr/bin/env python3
"""Build one contradiction and three key metrics for covered products."""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import time
import urllib.parse
import urllib.request
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import engine  # noqa: E402
OUTPUT = ROOT / "data" / "fundamentals.json"
CACHE = ROOT / "cache" / "fundamentals"
API = "https://zhiji-ai.xyz/commodity/api"
LIBRARY = "https://wangziquan-del.github.io/metals-framework/"

# metric tuple: id, name, unit, source, why it matters
FOCUS: dict[str, dict[str, Any]] = {
    "CU": {"route": "cu", "contradiction": "矿紧无解(TC深负)是长期底;短期定价在海外结构——伦铜Cash-3M强结构(挤仓式升水)+LME/COMEX价差(美铜关税套利)是主驱动;国内新边际在废铜:开票问题持续半年、计价系数97→99倒逼精铜替代。基调:偏多对待,回调买入,宏观冲击与伦铜结构松解(Back走平)是主要回撤源。", "marginal_focus": "LME Cash-3M结构|LME/COMEX价差(美铜关税)|废铜计价系数/开票政策|上海电解铜库存", "metrics": [
        ("FU00082249", "LME 铜投资基金净多", "手", "Mysteel", "投机集中度/挤仓风险"),
        ("ID01244863", "LME铜Cash-3M价差", "美元/吨", "Mysteel", "伦铜结构强弱(挤仓/升水)"),
        ("a12840187", "LME/COMEX铜价差", "美元/吨", "SMM", "美铜关税套利空间"),
        ("s20015675", "洋山铜溢价", "美元/吨", "SMM", "中国进口买盘是否回归")]},
    "AL": {"route": "al", "contradiction": "矛盾主线转向供给:国内8月消费急转弱(微观接单崩塌,库存显形要到9-10月),海外2027放量+369万吨方向不变但印尼节奏下修(电力是唯一约束,2028才是压力峰值),氧化铝先于电解铝放量压成本端。短期旺季回暖与库存拐点拉锯,中期天平向供给倾斜。基调:观望,等社库拐点确认后逢反弹偏空。", "marginal_focus": "铝棒加工费|社库拐点(9-10月)|俄铝进口增量|印尼机组/镍铁让电", "metrics": [
        ("ID00188307", "电解铝社会库存", "万吨", "Mysteel", "去库主线是否持续"),
        ("a10124317", "中国电解铝产量", "万吨", "SMM", "供应是否继续抬升"),
        ("a10031808", "铝型材开工率", "%", "SMM", "初端需求能否承接")]},
    "PB": {"route": "pb", "contradiction": "供需双弱:再生铅(废电瓶/环保)是供给脉冲,铅蓄电池旺季(秋冬)是需求验证窗口,LME铅边缘化不看。基调:区间震荡,等环保脉冲或旺季备货给方向。", "marginal_focus": "废电瓶价|再生铅开工|社库|电池旺季备货", "metrics": [
        ("a10134441", "LME 铅库存", "吨", "SMM", "海外压力是否缓解"),
        ("FU00015325", "SHFE 铅库存", "吨", "SHFE", "国内紧张程度"),
        ("a10017000", "再生铅开工率", "%", "SMM", "再生供应是否恢复")]},
    "ZN": {"route": "zn", "contradiction": "短期伦锌挤仓(低库存+深Back+高注销)托盘,中长期矿紧锭松错配(TC负值vs国内社库高)未解,内盘现货跟不动。基调:挤仓未结束前不空,发令枪=Back走平/库存回升/出口交仓。", "marginal_focus": "伦锌0-3 Back|LME库存/注销|沪伦比|国内社库", "metrics": [
        ("FU00082129", "LME 锌投资基金净多", "手", "Mysteel", "挤仓资金集中度"),
        ("a10097491", "LME 锌 0-3", "美元/吨", "SMM", "挤仓强度是否衰减"),
        ("ID00188329", "国内锌锭社库", "万吨", "Mysteel", "国内过剩能否消化")]},
    "NI": {"route": "ni", "contradiction": "供给过剩主线未改(印尼低成本放量、LME定价失真于印尼),沪镍贴近印尼现金成本,过剩逻辑在成本附近自我修正。边际变量:镍铁让电协商(落地=NPI隐性减产的利多期权)与硫磺成本传导,目前均未落地。基调:反弹即空、不追空,贴近成本收敛。", "marginal_focus": "镍铁让电协商|印尼NPI产量|LME/社库|不锈钢排产", "metrics": [
        ("a10018953", "纯镍社会库存", "吨", "SMM", "国内累库是否减速"),
        ("a10193590", "印尼 NPI 产量", "万镍吨", "SMM", "边际供应是否收缩"),
        ("s20019092", "金川镍升贴水", "元/吨", "SMM", "低价下现货是否转紧")]},
    "SN": {"route": "sn", "contradiction": "「供应紧」与「需求弱」并存,但目前供应更弱:矿端(缅甸未放量+TC低位)叙事仍在但边际钝化,现货已转松(隐形库存回升、升水回落);需求端结构分化大于总量,9-10月(开工率+库存方向)是关键验证期。当前驱动不在产业边际——下有40万补库支撑、上缺新驱动,锡已金融化为SPX的Beta。基调:高位宽幅震荡,区间思路,回调做多优于追涨。", "marginal_focus": "缅甸月进口(回万吨=证伪)|社库/隐形库存斜率|40万补库线|焊料开工率", "metrics": [
        ("ID01517441", "锡锭社会库存", "吨", "Mysteel", "现货紧张是否延续"),
        ("ID01538256", "云南 40% 锡矿 TC", "元/吨", "Mysteel", "矿端松紧是否拐点"),
        ("FU00082093", "LME 锡投资基金净多", "手", "Mysteel", "投机集中度/挤仓风险")]},
    "LC": {"route": "li", "contradiction": "供应过剩(高排产+高库存)vs政策托底(反内卷/减产),反弹是政策驱动非需求,现货停摆。基调:155,000之下按反弹对待,政策证真才谈反转。", "marginal_focus": "减产执行|排产/库存|155,000验证位|现金成本线", "metrics": [
        ("a12715547", "碳酸锂周度产量", "吨", "SMM", "供应出清速度"),
        ("a10172022", "碳酸锂样本总库存", "吨", "SMM", "存量过剩消化速度"),
        ("FU00058102", "广期所碳酸锂仓单", "手", "GFEX", "可交割压力是否下降")]},
    "SI": {"route": "si", "contradiction": "需求被多晶硅过剩拖累、无独立行情;供给故事升级——某大厂东部外购电优惠取消拟停20+台炉并封盘,但西部或全复产对冲,净减量待验证。基调:区间内跟随多晶硅情绪波动,减产落地量定方向。", "marginal_focus": "大厂停炉落地量|社库|多晶硅排产|电价", "metrics": [
        ("FU00050831", "广期所工业硅仓单", "手", "GFEX", "交割压力是否见顶"),
        ("ID01448337", "中国工业硅产量", "吨", "Mysteel", "供应是否真实收缩"),
        ("a12811428", "下游工业硅原料库存", "万吨", "SMM", "下游是否开始补库")]},
    # ---- 黑色（2026-08-13 加入，ID 经 bindings 实测）----
    "RB": {"route": "", "contradiction": "高炉现金利润已亏损、社库低于往年，但建材成交仍淡；关键看低利润逼减产先落地，还是旺季需求先验证。", "metrics": [
        ("ID00183781", "35城螺纹社库", "万吨", "Mysteel", "库存水位与去化方向"),
        ("ID00183169", "全国建材成交量", "吨", "Mysteel", "真实需求强弱"),
        ("ID01975884", "螺纹高炉现金利润", "元/吨", "Mysteel", "减产压力有多大")]},
    "I": {"route": "", "contradiction": "45 港库存高位对着高铁水；关键看铁水维持多久——铁水一拐，高港存就变成压力。", "metrics": [
        ("ID00186052", "45港铁矿石库存", "万吨", "Mysteel", "港口压力"),
        ("ID00184088", "247家日均铁水", "万吨", "Mysteel", "需求总阀门"),
        ("ID00183109", "247家高炉开工率", "%", "Mysteel", "开工是否拐头")]},
    "J": {"route": "", "contradiction": "吨焦亏损vs产量仍高是底色;边际:传焦协决议8/20起提涨50-55元/吨(湿熄/干熄)+自律控产,由安监停产、成本抬升引发,落地看焦企执行与钢厂接受度。基调:成本推动的提涨博弈,震荡偏强但高度看落地。", "marginal_focus": "焦协提涨落地|吨焦利润|铁水产量|钢厂接受度", "metrics": [
        ("ID00184171", "独立焦化厂吨焦利润", "元/吨", "Mysteel", "亏损深度"),
        ("ID00187978", "230家焦炭日均产量", "万吨", "Mysteel", "供应是否收缩"),
        ("FU00024294", "焦炭基差", "元/吨", "Mysteel", "现货跟不跟盘面")]},
    "JM": {"route": "", "contradiction": "蒙煤通关高位压制vs主焦已贴成本区;边际:湖南矿难点燃安监预期,但核查事故矿为无烟煤(非炼焦煤)、湖南储量仅0.3%——供给实质无损,纯情绪;山西安检已严、加严空间有限,09移仓多头止盈意愿强。基调:情绪脉冲对待,警惕反应过度后消退,趋势看通关与真实安监。", "marginal_focus": "安监政策|蒙煤通关|矿难后续扰动|移仓持仓", "metrics": [
        ("RE00024806", "甘其毛都通关车数", "车", "Mysteel", "蒙煤供应闸门"),
        ("ID00401840", "安泽低硫主焦价格", "元/吨", "Mysteel", "现货锚是否松动"),
        ("ID00184904", "炼焦煤进口（蒙古）", "吨", "海关", "进口趋势验证")]},
    # ---- 能化 ----
    "TA": {"route": "", "contradiction": "加工费被压在低位，但开工与产量仍高；关键看低加工费能否逼出检修，把库存拐点等来。", "metrics": [
        ("ID01214625", "PTA 加工费", "元/吨", "隆众", "利润压缩程度"),
        ("RE00033616", "PTA 产量", "万吨", "隆众", "供应是否收缩"),
        ("RE00033615", "PTA 行业库存", "万吨", "隆众", "累库拐点")]},
    "V": {"route": "", "contradiction": "电石法毛利深度亏损、社库仍高；关键看亏损减产与旺季去库谁先兑现。", "metrics": [
        ("ID02326533", "PVC 电石法毛利率", "%", "隆众", "亏损深度"),
        ("ID01990129", "PVC 社会库存", "万吨", "隆众", "库存压力"),
        ("ID01230718", "PVC 产能利用率", "%", "隆众", "供应弹性")]},
    "MA": {"route": "", "contradiction": "内地开工高位而港口库存低；关键看 MTO 利润能否撑住需求，接住内地来的货。", "metrics": [
        ("ID02070872", "焦炉气制甲醇开工率", "%", "隆众", "供应强度"),
        ("ID01733685", "焦炉气制甲醇产量", "吨", "隆众", "产量验证"),
        ("ID01371740", "MTO 生产毛利", "元/吨", "隆众", "下游承接力")]},
    "SA": {"route": "", "contradiction": "纯碱产量高位而玻璃需求走平；关键看高供应是继续累库，还是出口与轻碱需求接住。", "metrics": [
        ("ID01037477", "纯碱周度产量", "万吨", "隆众", "供应压力"),
        ("FU00024313", "纯碱基差", "元/吨", "Mysteel", "现货强弱"),
        ("ID01230657", "浮法玻璃开工率", "%", "隆众", "下游需求")]},
    # ---- 农产品 ----
    "M": {"route": "", "contradiction": "大豆压榨量高位、豆粕库存仍升；关键看高压榨是追上需求，还是把库存继续推高。", "metrics": [
        ("ID01709995", "油厂大豆压榨量", "万吨", "Mysteel", "供应强度"),
        ("ID01709989", "油厂豆粕库存", "万吨", "Mysteel", "累库速度"),
        ("ID00188062", "进口大豆港口库存", "万吨", "Mysteel", "原料到港压力")]},
    "LH": {"route": "", "contradiction": "自养深度亏损而出栏体重仍高；关键看亏损是去产能的开始，还是二育压栏把供应后移。", "metrics": [
        ("ID01208659", "商品猪出栏均价", "元/公斤", "涌益系", "价格水位"),
        ("ID01208800", "出栏平均体重", "公斤", "涌益系", "压栏程度"),
        ("ID01208822", "生猪自养利润", "元/头", "Mysteel", "亏损深度")]},
    "C": {"route": "", "contradiction": "饲料企业库存天数回升而深加工库存仍低；关键看新季上市前，渠道是主动补库还是被动累库。", "metrics": [
        ("ID01528411", "饲料企业库存天数", "天", "Mysteel", "渠道补库意愿"),
        ("ID00262726", "深加工企业玉米库存", "万吨", "Mysteel", "工业库存水位"),
        ("ID00404038", "玉米淀粉开机率", "%", "Mysteel", "工业需求")]},
    "SR": {"route": "", "contradiction": "配额内进口利润高企、进口到港预期压制盘面；关键看利润兑现成多少实际到港。", "metrics": [
        ("ID01201856", "巴西糖配额内进口利润", "元/吨", "Mysteel", "进口动力"),
        ("ID01519879", "白糖期现价差（南宁）", "元/吨", "Mysteel", "现货强弱")]},
    "P": {"route": "", "contradiction": "进口利润修复、商业库存回升；关键看马棕产量高峰过去后，库存是继续回补还是再度转紧。", "metrics": [
        ("ID01529070", "棕榈油商业库存", "万吨", "隆众", "库存回补速度"),
        ("ID01446102", "棕榈油进口利润", "元/吨", "Mysteel", "进口窗口"),
        ("ID01202668", "油菜籽压榨量", "万吨", "Mysteel", "油脂替代供应")]},
    "JD": {"route": "", "contradiction": "存栏高位(12.85亿只,补栏增)+产能释放vs中秋旺季需求(备货8月中下旬)——近月强远月弱;JD2610深贴水现货-16%显示盘面已price in节后崩,空远期别碰近月。", "marginal_focus": "存栏/补栏|现货价|基差|淘汰量", "metrics": [
        ("FU00039356", "鸡蛋基差", "元/吨", "DCE", "现货强弱"),
        ("ID01362874", "蛋鸡综合养殖盈利", "元/羽", "Mysteel", "利润方向"),
        ("ID01362852", "鸡蛋库存", "天", "Mysteel", "渠道库存")]},
}

# 全板块矛盾卡扩展（2026-08-13：能化 20 + 黑色剩余/贵金属 9 + 农产品 11，ID 均经 series 实测）
try:
    from _focus_frag_nenghua import FOCUS_FRAG as _FRAG_NH
    from _focus_frag_blackpm import FOCUS_FRAG as _FRAG_BP
    from _focus_frag_agri import FOCUS_FRAG as _FRAG_AG
    for _frag in (_FRAG_NH, _FRAG_BP, _FRAG_AG):
        FOCUS.update(_frag)
except ImportError as _e:
    print(f"[warn] focus 片段未加载: {_e}")


# 配图选择：矛盾轴心指标（不必是库存，由矛盾把握决定）；未列出的品种默认首指标/库存
CHART_PICK = {
    "CU": "ID01244863", "AL": "ID00188307", "PB": "a10134441", "ZN": "a10097491",
    "NI": "a10193590", "SN": "ID01517441", "LC": "a12715547", "SI": "ID01448337",
    "RB": "ID01975884", "I": "ID00184088", "J": "ID00184171", "JM": "RE00024806",
    "TA": "ID01214625", "V": "ID02326533", "MA": "ID01371740", "SA": "ID01037477",
    "M": "ID01709995", "LH": "ID01208822", "C": "ID01528411", "SR": "ID01201856",
    "P": "ID01529070", "JD": "ID01362874",
    "HC": "ID01975885", "SF": "ID00392264", "SM": "ID01105168", "SS": "a10019689",
    "WR": "ID00187681", "AU": "ID00302666", "AG": "ID00302665", "PD": "FU00078785", "PT": "FU00078767",
    "SC": "ID00189013", "FU": "ID00151664", "LU": "ID01214577", "BU": "ID01214582",
    "UR": "ID01037476", "SH": "ID01649092", "PP": "ID01230768", "L": "ID01001970",
    "EB": "RE00010181", "PL": "ID01368067", "PX": "a10179335", "EG": "ID02343958",
    "BZ": "ID01370025", "PF": "ID01230765", "PR": "ID01230656", "FG": "RE00033442",
    "RU": "RE00009776", "BR": "ID00393398", "NR": "RE00009774", "SP": "ID01370598",
    "A": "ID00188062", "B": "ID00188062", "Y": "ID02343777", "RM": "ID01030576",
    "OI": "ID01218965", "CS": "ID01197967", "CF": "ID01218979", "AP": "ID01202196",
    "CJ": "ID01244074", "PK": "ID01216483", "LG": "ID01881060",
}
NON_PHYSICAL_SECTORS = {"金融", "其他"}
NON_PHYSICAL_SYMBOLS = {"ZC"}
SEARCH_ALIASES = {"AG":"白银","AU":"黄金","PD":"钯","PT":"铂","HC":"热轧板卷","I":"铁矿石","J":"焦炭","JM":"焦煤","RB":"螺纹钢","SF":"硅铁","SM":"锰硅","WR":"线材","BR":"丁二烯橡胶","BU":"沥青","BZ":"纯苯","EB":"苯乙烯","EG":"乙二醇","FG":"玻璃","FU":"燃料油","L":"聚乙烯","LU":"低硫燃料油","MA":"甲醇","PF":"短纤","PG":"液化气","PL":"丙烯","PP":"聚丙烯","PR":"瓶片","PX":"对二甲苯","SA":"纯碱","SC":"原油","SH":"烧碱","TA":"PTA","UR":"尿素","V":"PVC","A":"豆一","AP":"苹果","B":"豆二","C":"玉米","CF":"棉花","CJ":"红枣","CS":"玉米淀粉","JD":"鸡蛋","LG":"原木","LH":"生猪","M":"豆粕","NR":"20号胶","OI":"菜油","P":"棕榈油","PK":"花生","RM":"菜粕","RU":"天然橡胶","SP":"纸浆","SR":"白糖","Y":"豆油"}
INVENTORY_PREFERRED = {"JD":"ID01362852"}
INVENTORY_CACHE = CACHE / "inventory-map.json"


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default



# 调研纪要精缩(单品种<=100字, 详情页"最新调研纪要及矛盾整理"折叠块; 改这里, 不改JSON)
SURVEY_NOTES: dict[str, str] = {
    "SN": "华南(8/14):下游库存压至10-15天刚需采购,40万以下才有补货意愿;消费电子量平+单耗趋势下滑,IGBT/光伏订单翻倍。周报(8/15):隐形库存+3,600吨、升水回落,现货转松。",
    "AL": "华南(8/14):升水强系到货少非需求好,铝棒接单9万吨→半月不足2万吨,9-10月库存显形,俄铝进口有增量。印尼(8月):投产约束在电力非政策,2027增量下修至135万吨,镍铁让电若谈成则上修。",
    "CU": "华南(8/14):废铜开票问题持续半年为历年最长,带票货供不应求、计价系数97→99;国产废铜被阳极板厂抢光,精废收窄倒逼精铜替代,构成实质支撑。",
    "NI": "印尼(8月):哈利达12万吨MHP+30万吨镍铁生产正常,硫磺库存3-4个月(加拿大补充);镍铁让电给电解铝协商无果——若落地=NPI隐性减产,铝镍双向变量。",
    "AO": "印尼(8月):铝土矿配额(RKAB一年一批)卡产量,南山400万吨仅运行300万吨;2027新增约217万吨(南山恢复为假设+齐力爬产),矿FOB仅33美元,配额放松则放量提前。",
    "SI": "小作文(8/16):某大厂东部外购电优惠电价取消,拟停全部外购电炉20+台、对部分铝厂封盘停报;但西部或全复产对冲——净减量待验证,现货情绪先紧。",
    "PS": "小作文(8/16):TH追买1-2000吨硅料(传期货部门做多配合),是仅有的追涨下游;其余下游借美12.4关税前涨价清库存(最晚10月出口、或转口换产地证)不囤货,11月后看淡;硅片或冲1.5(硅料容忍6万)但或脱节。",
    "J": "小作文(8/16):传山西焦协决议8/20零点起湿熄提涨50、干熄55元/吨,倡焦企统一执行+自律控产;起因主产地安监停产、焦煤成本抬升。落地看执行与钢厂接受度。",
    "SH": "山东调研(8/10-13,内部):行业亏损、降负常态化但未大规模停;头部氧化铝厂库存接近合理上限,外矿占比提升压制碱耗;出口量价双弱;液氯挺价托底。现货近底,远月累库偏空,2028年前难出清。",
    "JM": "小作文核查(8/16):湖南涟源杨梅山矿难矿种为低灰中硫无烟煤(动力/民用),非炼焦煤,湖南储量仅占全国0.3%——供给无实质影响,纯安监情绪;山西安检已严、加严空间有限,警惕情绪消退。",
}

CONTRADICTIONS = {
    'AG': '实际利率2.4%压制+无央行购金缓冲(贵金属弱腿),金银比68-70高位——纯宏观,看美债/美元/美国数据;基调:弱于金,跟随实际利率。',
    'AU': '实际利率压制vs央行购金托底(~1000吨/年)+避险,金脱离商品周期独立走强——纯宏观;基调:回调看多,购金托底。',
    'AO': '国内矿紧推价vs自身产能充足,传导有限;核心边际在海外——印尼2027新增约217万吨(瓶颈是RKAB配额而非矿),氧化铝先于电解铝放量,过剩方向明确。基调:反弹偏空,配额放松是加速器。',
    'SS': '产能过剩+需求(表需+10%)vs成本(镍)下移——过剩压顶、成本支撑;基调:反弹偏空,成本线有底。',
    'PS': '政策协同底(协会会:不低于完全成本销售+联合减产)vs过剩现实+需求透支(关税前抢出口清库存);配额130万吨争议大、落地存疑,下游仅TH追买(传期货配合)其余不囤货;硅片或冲1.5(对应硅料容忍6万)但上游传到一定程度会脱节不跟涨。基调:政策博弈震荡,协同证真前按反弹对待,11月后需求看空。',
    'PK': '供应宽松+油厂收购谨慎,基差Contango(-862)显示现货弱于盘面——油厂收购是锚;基调:震荡偏弱,看油厂收购节奏。',
    'BC': '保税区库存+进口盈亏+LME/COMEX价差,内外联动,保税库存是缓冲;基调:跟随铜主线,走内外套利逻辑。',
    'AD': '再生铝成本(废铝)驱动+压铸需求(汽车/家电)vs电解铝价差,供需紧平衡;基调:区间震荡,跟废铝成本。',
    'PD': '汽车催化需求+南非/俄供给,需求结构性走弱(燃油车占比降);基调:弱势震荡。',
    'PT': '氢能+首饰+汽车催化,供给(南非)vs需求结构;基调:供需双弱,震荡。',
    'A': '国产豆新季产量+政策收储托底vs压榨/食用需求,供应宽松;基调:宽松压制、收储托底,区间震荡。',
    'B': '进口大豆到港成本(美豆/南美)+压榨利润,供应宽松vs压榨需求;基调:到港成本定价,震荡。',
    'AP': '新季套袋/坐果定产量,冷库旧果去化vs新果上市,季节性博弈;基调:新季产量定方向,区间。',
    'CF': '新棉产量+纺企补库+抛储,供应宽松vs需求偏弱;基调:震荡偏弱。',
    'CJ': '新季坐果定产量+现货走货,丰产预期压制;基调:反弹偏空。',
    'CS': '玉米成本+开工vs下游(造纸/食品)需求,成本支撑;基调:区间震荡,成本有底。',
    'RM': '加拿大菜籽+养殖(水产/猪)需求,供给收紧vs需求;基调:震荡偏强。',
    'Y': '大豆压榨+油脂需求(餐饮/生物柴油),供应与需求;基调:跟随压榨节奏,震荡。',
    'OI': '加拿大菜籽供应(反倾销)+压榨,供给收紧vs需求偏弱;基调:供给支撑,震荡偏强。',
    'SC': 'OPEC减产/增产+地缘(中东)+需求,供给与地缘定价;基调:事件驱动高波动,区间。',
    'BU': '基建/道路需求淡季+炼厂开工,累库压制,等旺季;基调:淡季偏空,等旺季。',
    'FU': '高硫裂解+船燃需求+中东/俄罗斯供应,地缘与季节性;基调:跟随裂解价差,震荡。',
    'LU': '船燃需求+调和成本,供应宽松;基调:震荡偏弱。',
    'PG': '沙特CP价+燃烧/化工(PDH)需求,季节性(冬季燃烧旺);基调:CP+季节性,冬季前区间震荡。',
    'EG': '煤制/油制成本+库存高位vs聚酯需求,供给过剩压制;基调:反弹偏空。',
    'EB': '纯苯成本+自身开工vsPS/ABS/丁苯需求,成本主导;基调:跟随成本,震荡。',
    'BZ': '石脑油成本+芳烃利润vs下游(苯乙烯/己内酰胺)需求,成本定价;基调:成本定价,震荡。',
    'PF': 'PTA成本+纺服需求,成本支撑vs需求淡季;基调:成本有底、需求压制,震荡。',
    'PR': 'PTA/MEG成本+聚酯瓶片出口需求,成本与需求博弈;基调:震荡。',
    'PX': '石脑油成本+PTA需求+调油,成本与需求博弈;基调:震荡,跟PTA链条。',
    'PP': '原油成本+库存vs塑编/注塑需求,供需宽松;基调:震荡偏弱。',
    'PL': '原油+聚丙烯需求,成本定价;基调:跟随成本,震荡。',
    'BR': '丁二烯成本+顺丁胶供给vs轮胎需求,成本与需求博弈;基调:震荡。',
    'RU': '泰国/印尼供给+轮胎需求,天气(厄尔尼诺)扰动;基调:天气+需求双驱动,区间。',
    'NR': '泰国杯胶/胶水成本+轮胎需求,成本支撑vs需求季节性;基调:成本有底,区间震荡。',
    'FG': '地产竣工需求弱+纯碱成本+冷修供给收缩,供需双弱底部震荡;基调:底部震荡,等冷修或竣工。',
    'UR': '煤价成本+农需(春耕/秋播)+出口政策,成本与季节性;基调:季节性区间。',
    'SH': '行业全面亏损(折百约1920vs财务成本1800-2100)但降负不全停,磨底格局;矛盾=累库方向确定(下半年新增产能约100万吨+外矿替代压制碱耗+出口走弱)vs液氯挺价托底(氯碱综合算账)。边际:头部铝厂库存接近合理上限、仓单1900上方压力渐显、9月大厂检修预期。基调:短期磨底震荡,10月后或阶段修复,远月01偏空。',
    'SP': '海外浆价(巴西/加拿大)+纸厂需求+库存,供需双弱;基调:震荡。',
    'HC': '制造业(汽车/机械/出口)需求+铁水成本vs高炉减产,供需平衡偏松;基调:跟随铁水,震荡偏弱。',
    'WR': '建材需求弱+钢厂减产,供需双弱;基调:震荡。',
    'SF': '电力成本+钢厂需求+双控政策,成本支撑;基调:成本有底,震荡。',
    'SM': '锰矿成本+钢厂需求+双控,成本与需求博弈;基调:震荡。',
    'ZC': '电厂日耗+港口库存+政策(保供),季节性(迎峰度夏);基调:季节性,看日耗。',
    'LG': '建筑需求+进口(新西兰/欧洲),需求疲弱vs供应充足;基调:震荡偏弱。',
    'EC': '欧线运价(SCFI)+运力供需(红海绕行/新船交付),运价弹性大;基调:事件驱动,高波动。',
    'IF': '沪深300,看宏观流动性/大盘盈利/风险偏好;基调:宏观贝塔。',
    'IH': '上证50,看大金融/宏观流动性;基调:宏观贝塔。',
    'IC': '中证500,看宏观流动性/中小盘盈利;基调:宏观贝塔。',
    'IM': '中证1000,看中小盘/微盘流动性;基调:宏观贝塔,弹性最大。',
    'T': '10年国债,看利率/货币政策/经济数据;基调:利率驱动。',
    'TF': '5年国债,看利率/货币政策;基调:利率驱动。',
    'TS': '2年国债,看资金面/短端利率;基调:利率驱动。',
    'TL': '30年国债,看长端利率/久期;基调:利率驱动,久期弹性。',
}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    temp.replace(path)


def api_key() -> str:
    key = os.environ.get("ZHIJI_DATA_KEY") or os.environ.get("ZHIJI_GUAN_KEY") or ""
    if key:
        return key.strip()
    config = load_json(ROOT / "config.local.json", {})
    return str(config.get("data_key") or config.get("guan_key") or "").strip()


def parse_day(value: Any) -> date | None:
    try:
        return datetime.fromisoformat(str(value)[:10]).date()
    except (TypeError, ValueError):
        return None


def cadence(points: list[tuple[date, float]]) -> tuple[str, int, int]:
    gaps = [(b[0] - a[0]).days for a, b in zip(points[-13:-1], points[-12:]) if b[0] > a[0]]
    gap = statistics.median(gaps) if gaps else 30
    if gap <= 3:
        return "日", 5, 10
    if gap <= 10:
        return "周", 4, 21
    if gap <= 45:
        return "月", 3, 70
    return "季", 1, 150


def fetch_payload(metric_id: str, key: str) -> dict[str, Any]:
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{metric_id}.json"
    cached = load_json(path, {})
    if path.exists() and time.time() - path.stat().st_mtime < 1800 and cached.get("points"):
        return cached
    if not key:
        if cached.get("points"):
            return cached
        raise RuntimeError("未配置商品数据 API key")
    query = urllib.parse.urlencode({"id": metric_id, "start": "2023-01-01", "end": date.today().isoformat()})
    request = urllib.request.Request(f"{API}/series?{query}", headers={"X-Data-Key": key, "User-Agent": "YAFCO-Fundamental-Focus/1.0"})
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if not payload.get("points"):
                raise RuntimeError(str(payload.get("error") or "空序列"))
            write_json(path, payload)
            return payload
        except Exception as error:  # noqa: BLE001
            last_error = error
            time.sleep(1.2 * (attempt + 1))
    if cached.get("points"):
        return cached
    raise RuntimeError(str(last_error))


def search_inventory(product: dict[str, Any], key: str) -> dict[str, Any] | None:
    symbol = str(product.get("symbol") or product.get("product") or "").upper()
    if product.get("sector") in NON_PHYSICAL_SECTORS or symbol in NON_PHYSICAL_SYMBOLS:
        return None
    cached_map = load_json(INVENTORY_CACHE, {})
    cached = cached_map.get(symbol)
    if cached and cached.get("id"):
        return cached
    query_name = SEARCH_ALIASES.get(symbol) or str(product.get("name") or symbol).removeprefix("沪")
    if not key:
        return None
    url = f"{API}/search?" + urllib.parse.urlencode({"q": f"{query_name} 库存", "source": "all", "limit": 12})
    request = urllib.request.Request(url, headers={"X-Data-Key": key, "User-Agent": "YAFCO-Inventory-Snapshot/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            results = json.loads(response.read().decode("utf-8")).get("results") or []
    except Exception:
        return cached
    preferred = INVENTORY_PREFERRED.get(symbol)
    choice = next((x for x in results if x.get("id") == preferred), None) if preferred else None
    if not choice:
        def rank(item: dict[str, Any]) -> float:
            text = f"{item.get('name','')} {item.get('path','')}"
            if "库存" not in text or query_name not in text:
                return -100
            score = 3 + (4 if any(w in text for w in ("中国","全国","总库存","总量","社会库存")) else 0)
            score += 2 if any(w in text for w in ("仓单","交易所库存","库存可用天数")) else 0
            score -= 5 if any(w in text for w in ("省","市","港：","企业：","样本：")) else 0
            score -= 3 if any(w in text for w in ("原料库存","下游","产成品")) else 0
            return score
        ranked = sorted(results, key=rank, reverse=True)
        choice = ranked[0] if ranked and rank(ranked[0]) >= 3 else None
    if not choice:
        return None
    selected = {"id":choice.get("id"),"name":choice.get("name"),"unit":choice.get("unit") or "","source":str(choice.get("source") or "知几·料").upper(),"path":choice.get("path")}
    cached_map[symbol] = selected
    write_json(INVENTORY_CACHE, cached_map)
    return selected


def summarize_inventory(product: dict[str, Any], key: str, previous: dict[str, Any] | None) -> dict[str, Any]:
    selected = search_inventory(product, key)
    if not selected:
        return {"status":"unmatched","latest":None,"name":"库存口径待匹配","source":"知几·料"}
    result = summarize((selected["id"],selected["name"],selected.get("unit") or "",selected.get("source") or "知几·料","基础库存"), key, previous)
    result["path"] = selected.get("path")
    return result


def build_spread(product: dict[str, Any]) -> dict[str, Any]:
    lead = str(product.get("contract") or "")
    try:
        curve = engine.curve_quotes(str(product.get("symbol") or ""), lead)
    except Exception as error:
        return {"status":"failed","value":None,"error":str(error)[:120]}
    if not curve:
        return {"status":"unavailable","value":None}
    near = next((x for x in curve if x.get("is_lead")), None) or max(curve,key=lambda x:float(x.get("open_interest") or 0))
    following = [x for x in curve if str(x.get("symbol") or "").upper()>str(near.get("symbol") or "").upper() and (x.get("open_interest") or 0)>0]
    if not following:
        return {"status":"no_far_contract","value":None,"near_symbol":str(near.get("symbol") or "").upper()}
    far = max(following,key=lambda x:(float(x.get("open_interest") or 0),float(x.get("volume") or 0)))
    value = float(near["last"])-float(far["last"])
    return {"status":"ok","definition":"主力－下一活跃合约","value":round(value,6),"near_symbol":str(near.get("symbol") or "").upper(),"near_price":near["last"],"far_symbol":str(far.get("symbol") or "").upper(),"far_price":far["last"],"structure":"近强·BACK" if value>0 else ("远强·CONTANGO" if value<0 else "平水"),"source":"知几·观","end":date.today().isoformat()}


def summarize(metric: tuple[str, str, str, str, str], key: str, previous: dict[str, Any] | None) -> dict[str, Any]:
    metric_id, name, unit, source, why = metric
    try:
        payload = fetch_payload(metric_id, key)
        values: dict[date, float] = {}
        for point in payload.get("points") or []:
            day = parse_day(point.get("date"))
            try:
                value = float(point.get("value"))
            except (TypeError, ValueError):
                continue
            if day and math.isfinite(value):
                values[day] = value
        points = sorted(values.items())
        if len(points) < 2:
            raise RuntimeError(f"仅 {len(points)} 个有效点")
        freq, lookback, max_age = cadence(points)
        lookback = min(lookback, len(points) - 1)
        latest_day, latest = points[-1]
        previous_day, previous_value = points[-1 - lookback]
        recent = [abs(value) for _, value in points[-12:] if value != 0]
        scale = max(abs(previous_value), statistics.median(recent or [1.0]), 1e-9)
        step = max(1, len(points) // 130)
        slim = points[::step]
        if slim[-1][0] != points[-1][0]:
            slim = slim + [points[-1]]
        return {
            "id": metric_id, "name": name, "unit": unit, "source": source, "why": why,
            "latest": round(latest, 6), "end": latest_day.isoformat(),
            "change_pct": round((latest - previous_value) / scale * 100, 2),
            "comparison": f"较{lookback}{freq}前",
            "stale": (date.today() - latest_day).days > max_age,
            "status": "ok", "points": len(points), "previous_end": previous_day.isoformat(),
            "series": [[d.isoformat(), round(v, 6)] for d, v in slim],
        }
    except Exception as error:  # noqa: BLE001
        if previous and previous.get("latest") is not None:
            fallback = dict(previous)
            fallback.update({"status": "fallback", "error": str(error)[:160]})
            return fallback
        return {
            "id": metric_id, "name": name, "unit": unit, "source": source, "why": why,
            "latest": None, "end": None, "change_pct": None, "comparison": "",
            "stale": True, "status": "failed", "error": str(error)[:160],
        }


def build(workers: int) -> dict[str, Any]:
    market = load_json(ROOT / "data" / "market.json", {})
    products = market.get("products") or []
    if not products:
        raise SystemExit("data/market.json is empty")
    old = load_json(OUTPUT, {})
    old_metrics = {
        item.get("id"): item
        for product in old.get("products") or []
        for item in product.get("metrics") or []
        if item.get("id")
    }
    old_products = {str(item.get("symbol") or "").upper(): item for item in old.get("products") or []}
    configs = {item[0]: item for config in FOCUS.values() for item in config["metrics"]}
    results: dict[str, dict[str, Any]] = {}
    key = api_key()
    with ThreadPoolExecutor(max_workers=max(1, min(workers, 8))) as pool:
        futures = {
            pool.submit(summarize, item, key, old_metrics.get(metric_id)): metric_id
            for metric_id, item in configs.items()
        }
        for future in as_completed(futures):
            metric_id = futures[future]
            results[metric_id] = future.result()
            print(f"[fundamental] {metric_id}: {results[metric_id]['status']}", flush=True)

    output_products = []
    for product in products:
        symbol = str(product.get("symbol") or "").upper()
        config = FOCUS.get(symbol)
        if not config:
            spread = build_spread(product)
            previous_inventory = (old_products.get(symbol) or {}).get("inventory")
            inventory = summarize_inventory(product, key, previous_inventory)
            inventory_ok = inventory.get("latest") is not None
            spread_ok = spread.get("value") is not None
            if product.get("sector") in NON_PHYSICAL_SECTORS or symbol in NON_PHYSICAL_SYMBOLS:
                inventory = {"status":"not_applicable","latest":None,"name":"库存不适用","source":"—"}
            auto_contra = "库存与月差数据待更新。"
            if inventory_ok:
                chg = inventory.get("change_pct")
                dir_txt = "累库" if (chg or 0) > 3 else ("去库" if (chg or 0) < -3 else "持平")
                struct = spread.get("structure") or spread.get("status") or "结构待更新"
                key_watch = "累库能否止步" if dir_txt == "累库" else ("去库能否延续" if dir_txt == "去库" else "库存方向选择")
                auto_contra = (f"{inventory.get('name','库存')}{dir_txt}（{inventory.get('comparison','')} "
                               f"{chg:+.1f}%），月差{struct}；关键看{key_watch}。（自动初判）")
            output_products.append({
                "symbol": symbol, "name": product.get("name"), "covered": inventory_ok or spread_ok,
                "kind": "market_snapshot", "summary": "库存验证现货松紧；主力－下一活跃合约验证期限结构。",
                "inventory": inventory, "spread": spread,
                "contradiction": CONTRADICTIONS.get(symbol) or auto_contra, "metrics": [], "library_url": LIBRARY,
                "survey": SURVEY_NOTES.get(symbol),
            })
            continue
        output_products.append({
            "symbol": symbol, "name": product.get("name"), "covered": True,
            "kind": "focus",
            "contradiction": CONTRADICTIONS.get(symbol) or config["contradiction"],
            "marginal_focus": config.get("marginal_focus"),
            "metrics": [results[item[0]] for item in config["metrics"]],
            "survey": SURVEY_NOTES.get(symbol),
            "chart_id": CHART_PICK.get(symbol),
            "library_url": f"{LIBRARY}#/c/{config['route']}",
        })

    payload = {
        "schema_version": 2,
        "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source": "知几·料（SMM/Mysteel 镜像）",
        "coverage": {"total": len(output_products), "covered": sum(bool(item.get("covered")) for item in output_products), "focus": len(FOCUS)},
        "products": output_products,
    }
    raw = json.dumps(payload, ensure_ascii=False, allow_nan=False)
    if "wk_" in raw or '"score"' in raw or '"consistency"' in raw:
        raise SystemExit("fundamentals output violated security/minimality rules")
    write_json(OUTPUT, payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    payload = build(args.workers)
    print(json.dumps({"updated_at": payload["updated_at"], **payload["coverage"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
