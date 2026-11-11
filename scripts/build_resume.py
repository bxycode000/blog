# -*- coding: utf-8 -*-
"""生成简历 DOCX（仅供本地投递，不再随站发布；再由 LibreOfficeKit 转 PDF）。

用法：
    python scripts/build_resume.py
    <libreoffice-kit-cli> convert --input _resume_build.docx --output _resume_build.pdf

修改简历内容时只改本脚本里的文案，然后重新执行上面两步。
产物含手机号与邮箱，不要放进 static/ 或提交仓库。
"""
import docx
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_TAB_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
import os

INK, RED, GREY, LIGHT = RGBColor(0x1c,0x1e,0x1b), RGBColor(0xa9,0x35,0x2a), RGBColor(0x5a,0x5d,0x56), RGBColor(0x6a,0x6d,0x66)
FONT = "Microsoft YaHei"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "_resume_build.docx")

doc = Document()
sec = doc.sections[0]
sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
sec.top_margin, sec.bottom_margin = Cm(1.25), Cm(1.15)
sec.left_margin, sec.right_margin = Cm(1.45), Cm(1.45)
CONTENT_W = Cm(21.0 - 1.45 * 2)

normal = doc.styles["Normal"]
normal.font.name = FONT
normal.font.size = Pt(9.6)
normal.element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
normal.paragraph_format.space_before = Pt(0)
normal.paragraph_format.space_after = Pt(0)
normal.paragraph_format.line_spacing = 1.28

def run(p, text, size=9.6, bold=False, color=INK):
    r = p.add_run(text); r.font.name = FONT
    r._element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
    r.font.size = Pt(size); r.bold = bold; r.font.color.rgb = color
    return r

def bottom_border(p, color="D7D4CC", sz="6"):
    pPr = p._p.get_or_add_pPr(); pBdr = OxmlElement("w:pBdr"); b = OxmlElement("w:bottom")
    b.set(qn("w:val"), "single"); b.set(qn("w:sz"), sz); b.set(qn("w:space"), "2"); b.set(qn("w:color"), color)
    pBdr.append(b); pPr.append(pBdr)

def heading(text):
    p = doc.add_paragraph(); p.paragraph_format.space_before = Pt(9); p.paragraph_format.space_after = Pt(3)
    run(p, text, 10.5, True, RED); bottom_border(p)

def bullet(text):
    p = doc.add_paragraph(style="List Bullet")
    p.paragraph_format.space_before = Pt(1); p.paragraph_format.space_after = Pt(1)
    p.paragraph_format.line_spacing = 1.28
    p.paragraph_format.left_indent = Cm(0.55); p.paragraph_format.first_line_indent = Cm(-0.35)
    run(p, text, 9.6)

def role(company, date, subtitle):
    p = doc.add_paragraph(); p.paragraph_format.space_before = Pt(5); p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.tab_stops.add_tab_stop(CONTENT_W, WD_TAB_ALIGNMENT.RIGHT)
    run(p, company, 10.4, True); run(p, "\t" + date, 8.6, False, LIGHT)
    p2 = doc.add_paragraph(); p2.paragraph_format.space_after = Pt(1); run(p2, subtitle, 9.0, False, GREY)

p = doc.add_paragraph(); p.paragraph_format.space_after = Pt(1); run(p, "陆懿", 23, True)
p = doc.add_paragraph(); p.paragraph_format.space_after = Pt(2)
run(p, "求职意向：亚马逊产品运营（Listing 打造 / 数据化运营 / 站内广告方向）", 10.5, True, RED)
p = doc.add_paragraph(); p.paragraph_format.space_after = Pt(0)
run(p, "合肥　|　" + os.environ.get("RESUME_PHONE", "手机号") + "　|　" + os.environ.get("RESUME_EMAIL", "邮箱") + "　|　2003.12　|　随时到岗", 8.8, False, GREY)
bottom_border(p, "171916", "12")

heading("核心优势")
for t in [
 "互联网 / 电商运营实习经历：在凯得盛商贸负责电商平台运营与销售数据整理分析，在科大讯飞负责产品运营与用户反馈闭环，覆盖数据整理、问题跟踪与方案落地全流程。",
 "数据敏感、工具扎实：熟练使用 Excel 搭建销售 / 库存 / 用户需求台账与周期报表；具备 SQL、Python 基础；善用 AI 工具提升数据处理与文案产出效率，习惯从数据中定位问题并推动优化。",
 "内容与素材能力：运营个人 B 站账号，累计播放 64.5 万，持续实践选题策划、标题与封面优化、评论互动与数据复盘；熟练使用 Photoshop / 剪映 / PR 处理图片与短视频素材。",
 "英语与学习能力：大学英语六级 551 分、四级 607 分（高于岗位 CET-4 要求），可流畅阅读英文资料；学习能力强，能快速掌握新平台与新工具并沉淀方法论。",
 "抗压、细致、执行力强：在日均 30+ 人次高强度沟通场景下保持稳定输出，多线程推进订单、库存与售后事务；坚持每日复盘与结构化总结，适应快节奏业务环境。",
]: bullet(t)

heading("实习经历")
role("科大讯飞股份有限公司", "2025.11 — 2026.03", "助理产品运营实习生")
for t in [
 "用户咨询与问题响应：通过电话、社媒等多渠道承接日均 30+ 人次咨询与投诉，完成问题受理、情绪安抚与方案答复，首次响应及时率保持 ≥98%。",
 "反馈闭环与流程优化：建立「用户反馈—分类分级—处理—回访」闭环机制，将零散投诉归纳为 5 类并沉淀标准话术，推动重复咨询率下降 20%。",
 "数据台账与产品洞察：运用 Excel 建立用户需求分类台账，累计输出用户洞察报告 4 份，其中 4 条产品优化建议被采纳并落地。",
 "转化提升：跟进用户关键行为数据，定位流失预警用户并主动触达，配合社媒与电话回访，推动产品转化率提升 15%、续报率提升 6%。",
 "文案与流程优化：优化引导文案与新手引导流程，降低新用户上手门槛，累计触达用户约 1000 人。",
]: bullet(t)
role("北京凯得盛商贸有限公司", "2025.07 — 2025.08", "运营助理实习生（互联网销售方向）")
for t in [
 "电商平台运营与推广：协助维护线上平台日常运营，整理销售数据并分析销售趋势，参与推广活动的策划与执行。",
 "商品与库存数据管理：维护 1300+ 商品与供应商价格台账，核对实物库存与系统台账，按日 / 周输出进销存与经营报表（累计 30 份），为选品与采购补货提供数据支持。",
 "订单流转与售后跟进：核对客户订单并跟进流转进度，对接采购、仓储、财务 3 个部门处理异常，闭环跟进售后退换 10 余笔，收集售后反馈并转交相关部门推动改进。",
]: bullet(t)

heading("校园实践经历")
role("合肥市鲁园行知学堂", "2024.07 — 2024.08", "实践负责人")
for t in [
 "需求调研与方案设计：设计家长调研问卷并逐户走访，识别「基础薄弱 + 缺乏监督」核心需求，制定「个性化辅导 + 学情反馈」服务方案，家长诉求全部前置化解。",
 "统筹协调与资源对接：负责实践课程编排与教学任务分配（按期完成率 100%），对接政府工作人员完成资源协调，保障项目顺利落地。",
 "实践成果获人民网、中国网等多家媒体报道，形成良好的项目口碑与社会反响。",
]: bullet(t)
role("「国元证券杯」安徽省大学生金融投资创新大赛", "2025.04 — 2025.06", "团队成员")
for t in [
 "市场与标的分析：运用财务分析模型开展上市可行性研究，独立完成行业与标的分析报告，为团队决策提供数据支撑。",
 "策略执行与复盘：制定并执行投资策略，管理 20 万元虚拟资金（组合区间涨幅超 20%），强化数据驱动决策与纪律化复盘习惯。",
]: bullet(t)

heading("教育背景")
p = doc.add_paragraph(); p.paragraph_format.space_after = Pt(1)
p.paragraph_format.tab_stops.add_tab_stop(CONTENT_W, WD_TAB_ALIGNMENT.RIGHT)
run(p, "合肥师范学院　|　经济与金融　|　全日制本科", 10.4, True)
run(p, "\t2022.09 — 2026.06", 8.6, False, LIGHT)
bullet("主修课程：微观经济学、宏观经济学、统计学、管理学、会计学。")
bullet("学业荣誉：校级三等奖学金、安徽省国际贸易技能大赛省级三等奖。")

heading("技能证书")
for t in [
 "语言能力：大学英语六级 551 分、四级 607 分（可流畅阅读英文资料）；普通话二级甲等；日语 N3。",
 "数据与办公：熟练使用 Word / Excel / PPT，擅长 Excel 台账搭建与数据处理；具备 SQL、Python 基础；熟练使用 AI 工具（Claude Code、Codex）辅助文案撰写与数据整理。",
 "内容与设计：熟练使用 Photoshop / 剪映 / PR，可独立完成图片处理与短视频剪辑；具备新媒体内容制作与数据复盘经验。",
 "证书荣誉：计算机二级；2025 全国大学生 AI 答题实践竞赛荣誉证书、全国高校 AI 应用创作大赛荣誉证书；高校心理委员 MOOC 认证。",
]: bullet(t)

heading("持续学习与自我提升")
bullet("岗位适配意愿：对产品运营、店铺运营与跨境电商方向有明确兴趣（电商运营实习 + 内容运营实践），持续关注行业动态。")
bullet("学习与复盘：具备快速学习新工具的能力，能将工具方法落地到实际工作；保持每日复盘与个人知识库沉淀习惯。")

doc.save(OUT)
print("saved", OUT)
