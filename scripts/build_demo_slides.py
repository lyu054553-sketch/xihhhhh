"""Build the Chinese demo deck from one source: HTML and editable PowerPoint.

Usage: .venv/Scripts/python.exe scripts/build_demo_slides.py
Optional dependency for PowerPoint: python-pptx.
"""

from html import escape
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SLIDES = [
    {
        "eyebrow": "INVENTORY CASH AGENT",
        "title": "让库存决策\n走到人工确认",
        "subtitle": "从门店反馈到执行草稿，一条可以核对的业务流程。",
        "points": ["发现库存异常与资金占用", "以证据、计算和约束支持决策", "以版本、审批和回执保留责任边界"],
        "note": "合成演示数据 · 当前为规则计算版本",
        "speaker": "我们解决多门店库存占资和协同处置的问题。今天展示合成数据上的真实接口交互，不把模拟测算说成客户收益，也不把规则工具说成真实大模型。",
    },
    {
        "eyebrow": "01 / PRODUCT",
        "title": "五个入口\n共用一条流程",
        "subtitle": "同一份事实、同一套后端计算、同一套人工审批。",
        "points": ["滞销诊断：事实、原因假设、证据与缺项", "跨店调拨：门店、数量、费用与安全库存", "近效期：正常销售、调拨、促销、退供", "采购刹车：库存、在途、未执行量与付款", "现金模拟：候选组合、业务约束与目标缺口"],
        "note": "已有业务入口与规则工具；真实模型适配仍待接入",
        "speaker": "五个入口不是五套后端。当前调用既有确定性接口，页面负责把输入、证据、结果和下一步连起来。",
    },
    {
        "eyebrow": "02 / WALKTHROUGH",
        "title": "反馈 → 诊断 → 调拨\n确认后生成执行草稿",
        "subtitle": "演示西湖文三店的合成库存案例。",
        "points": ["01  核对库存、销量与原因缺项", "02  留存反馈原文，人工检查返回草稿", "03  修改数量并请求后端重算", "04  保存方案、提交审批、负责人确认", "05  生成执行任务，后续回执另行记录"],
        "note": "输入改变需重算；任务创建不等于 ERP 已执行",
        "speaker": "先将数量改成100观察约束错误，再用默认参数中的40重算。实际结果以当前后端为准。保存审批后生成的是草稿，不会直接向ERP发货。",
    },
    {
        "eyebrow": "03 / MEASUREMENT",
        "title": "四种金额\n分别回答四个问题",
        "subtitle": "页面不会把库存搬动或预计报损减少当成现金回款。",
        "points": ["库存成本：这些货占用了多少成本？", "预计避免报损：处置可能减少多少损失？", "模拟净现金改善：期限内有哪些可计算现金事件？", "实际回款：是否已有财务或执行回执支持？"],
        "note": "未知保持未知；不相加生成虚构 ROI",
        "speaker": "这些指标边界不同。内部调拨改变库存位置，可能产生配送费；它本身不能证明现金释放。实际回款还需要外部证据。",
    },
    {
        "eyebrow": "04 / FAILURE STATES",
        "title": "失败要看得见\n旧结果不能继续用",
        "subtitle": "交互状态直接进入现有请求与单据生命周期。",
        "points": ["API 失败：显示错误、保留输入、显式重试", "快速切换：旧响应不能覆盖最后选择", "修改输入：旧计算和可提交状态立即失效", "约束不通过：展示原因，阻止下一步", "模型未接入：明确规则模式，不伪造推理轨迹"],
        "note": "前端交互保护不能替代服务端事务和权限控制",
        "speaker": "现场用浏览器离线模式展示一次失败，然后恢复重试。错误状态不是用一组样例数字填平，成功提示必须来自接口成功响应。",
    },
    {
        "eyebrow": "05 / REPRODUCIBILITY",
        "title": "同一场景\n能够重复验证",
        "subtitle": "固定种子、预期结果与独立演示库。",
        "points": ["场景覆盖滞销、临期、采购过量和门店缺货", "缺字段、零销量与库存冲突有明确预期", "测试检查工具结果、输入失效和错误恢复", "独立演示库只承载合成数据与演示记录", "通过数量与证据以本次运行报告为准"],
        "note": "场景文件与后端内置快照分开标注，生成文件不自动导入",
        "speaker": "测试场景与实际页面共享接口约束。生成器用于回放和验证，不会静默改写正在演示的数据库。测试数字必须从本次运行产生。",
    },
    {
        "eyebrow": "06 / OWNERSHIP",
        "title": "前端负责清楚呈现\n后端负责业务计算",
        "subtitle": "浏览器 → 同源 API → 领域工具 → 事实与方案版本。",
        "points": ["朱：五入口、表单、状态、确认、合成场景、测试和演示", "魏：模型适配、业务工具、数据库、事务与正式契约", "接口变化先写契约，再调整消费者", "zmj 分支完成朱的开发；双方在集成分支验收"],
        "note": "沿用模块化单体，不在前端复制业务算法",
        "speaker": "我们尊重代码所有权。朱的工作是展示接口与组织交互，后端的缺口会记录并交接，不通过前端补金额或增加假状态来绕开。",
    },
    {
        "eyebrow": "07 / NEXT",
        "title": "今天能演示的\n与下一步要完成的",
        "subtitle": "先交付可信的流程，再接入真实智能与真实执行。",
        "points": ["本次：合成场景、五入口、规则测算、人工审批、执行草稿", "模型：真实请求、结构校验、证据引用与失败恢复", "后端：重置保护、资源隔离、事务、版本冲突和权限", "集成：ERP 数据与执行回执、财务结果核验"],
        "note": "GitHub / lyu054553-sketch/xihhhhh · 分支 zmj",
        "speaker": "本次前端演示交付不等于整个八模块项目已完成。真实模型、生产权限事务和ERP连接仍然是后续集成工作。",
    },
]


def build_html() -> None:
    sections = []
    for index, item in enumerate(SLIDES, 1):
        title = escape(item["title"]).replace("\n", "<br>")
        points = "".join(f"<li>{escape(point)}</li>" for point in item["points"])
        sections.append(
            f'<section class="slide" aria-label="第 {index} 页"{ "" if index == 1 else " hidden"}>'
            f'<div class="eyebrow">{escape(item["eyebrow"])}</div><h1>{title}</h1>'
            f'<p class="subtitle">{escape(item["subtitle"])}</p><ul>{points}</ul>'
            f'<footer><span>{escape(item["note"])}</span><b>{index:02d} / {len(SLIDES):02d}</b></footer>'
            f'<details><summary>讲稿</summary><p>{escape(item["speaker"])}</p></details></section>'
        )
    html = '''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>库存现金智能体 · 演示稿</title><style>
:root{color-scheme:dark;font-family:"Microsoft YaHei","PingFang SC",sans-serif;background:#0d1723;color:#eef3f6}
*{box-sizing:border-box}body{margin:0;padding:24px}main{max-width:1240px;margin:auto}
.slide{position:relative;min-height:697px;padding:52px 64px 70px;border:1px solid #2b3b4b;background:#132232}
.slide[hidden]{display:none}.eyebrow{color:#9ad7b7;font-size:14px;font-weight:700;letter-spacing:.15em}
h1{font-size:50px;line-height:1.25;letter-spacing:-.025em;margin:24px 0 16px;max-width:1050px}
.subtitle{color:#bdcbd5;font-size:20px;line-height:1.5;margin:0 0 25px}ul{padding:0;list-style:none;margin:0}
li{padding:9px 0 9px 23px;font-size:20px;line-height:1.4;position:relative}li:before{content:"";width:5px;height:5px;background:#9ad7b7;position:absolute;top:20px;left:0}
footer{position:absolute;bottom:30px;left:64px;right:64px;display:flex;justify-content:space-between;gap:20px;border-top:1px solid #354656;padding-top:14px;font-size:12px;color:#b8c8d2}
footer b{white-space:nowrap;color:#9ad7b7}details{margin-top:20px;color:#b8c8d2;font-size:14px}details p{max-width:900px;line-height:1.6}
nav{display:flex;justify-content:center;align-items:center;flex-wrap:wrap;gap:12px;margin:16px auto;font-size:14px}
button,a{font:inherit;border:1px solid #4e6273;color:#eef3f6;border-radius:4px;background:#132232;padding:9px 16px;text-decoration:none;cursor:pointer}button:disabled{opacity:.4;cursor:default}button:focus-visible,a:focus-visible{outline:3px solid #9ad7b7}
@media(max-width:700px){body{padding:12px}.slide{padding:30px 24px 96px;min-height:calc(100vh - 115px)}h1{font-size:32px}.subtitle,li{font-size:17px}footer{left:24px;right:24px;bottom:22px;font-size:11px}}
@media print{@page{size:13.333in 7.5in;margin:0}body{padding:0}main{max-width:none}.slide,.slide[hidden]{display:block;width:13.333in;height:7.5in;min-height:0;break-after:page;padding:50px 64px;background:#fff;color:#122333;border:0;print-color-adjust:exact}.slide:last-child{break-after:auto}.eyebrow,footer b{color:#23704f}.subtitle,footer{color:#3b5366}li:before{background:#23704f}h1{font-size:48px}li{font-size:19px}nav,details{display:none}}
</style></head><body><main>''' + "\n".join(sections) + '''</main>
<nav aria-label="演示页控制"><button id="previous" type="button">上一页</button><span id="position" aria-live="polite"></span><button id="next" type="button">下一页</button><button id="print" type="button">打印 / PDF</button><a href="DEMO_SLIDES.pptx">下载 PowerPoint</a></nav>
<script>
const slides=[...document.querySelectorAll('.slide')];let current=0;
function show(index){current=Math.max(0,Math.min(slides.length-1,index));slides.forEach((slide,i)=>{slide.hidden=i!==current});document.querySelector('#position').textContent=`${current+1} / ${slides.length}`;document.querySelector('#previous').disabled=current===0;document.querySelector('#next').disabled=current===slides.length-1;document.title=`${current+1}/${slides.length} · 库存现金智能体演示稿`;}
document.querySelector('#previous').addEventListener('click',()=>show(current-1));document.querySelector('#next').addEventListener('click',()=>show(current+1));document.querySelector('#print').addEventListener('click',()=>window.print());document.addEventListener('keydown',event=>{if(['ArrowRight','PageDown'].includes(event.key)){event.preventDefault();show(current+1)}else if(['ArrowLeft','PageUp'].includes(event.key)){event.preventDefault();show(current-1)}});show(0);
</script></body></html>'''
    (ROOT / "docs/DEMO_SLIDES.html").write_text(html, encoding="utf-8")


def build_powerpoint() -> None:
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.util import Inches, Pt

    presentation = Presentation()
    presentation.slide_width = Inches(13.333)
    presentation.slide_height = Inches(7.5)
    presentation.core_properties.title = "库存现金智能体 · 规则版本演示"
    presentation.core_properties.subject = "合成数据 / 朱负责的前端交付 / zmj"
    presentation.core_properties.author = "库存现金智能体项目组"
    presentation.core_properties.language = "zh-CN"

    def text_box(slide, value, left, top, width, height, size, color, bold=False):
        shape = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
        frame = shape.text_frame
        frame.word_wrap = True
        frame.margin_left = frame.margin_right = 0
        frame.margin_top = frame.margin_bottom = 0
        for number, line in enumerate(value.split("\n")):
            paragraph = frame.paragraphs[0] if number == 0 else frame.add_paragraph()
            paragraph.text = line
            paragraph.font.name = "Microsoft YaHei"
            paragraph.font.size = Pt(size)
            paragraph.font.bold = bold
            paragraph.font.color.rgb = RGBColor.from_string(color)
            paragraph.space_after = Pt(5)
        return shape

    for index, item in enumerate(SLIDES, 1):
        slide = presentation.slides.add_slide(presentation.slide_layouts[6])
        slide.background.fill.solid()
        slide.background.fill.fore_color.rgb = RGBColor.from_string("132232")
        text_box(slide, item["eyebrow"], .68, .40, 12, .35, 13, "9AD7B7", True)
        text_box(slide, item["title"], .68, 1.00, 12, 1.55, 36, "EEF3F6", True)
        text_box(slide, item["subtitle"], .68, 2.70, 12, .55, 17, "BDCBD5")
        for row, point in enumerate(item["points"]):
            mark = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(.70), Inches(3.50 + row * .48), Inches(.045), Inches(.045))
            mark.fill.solid()
            mark.fill.fore_color.rgb = RGBColor.from_string("9AD7B7")
            mark.line.fill.background()
            text_box(slide, point, .90, 3.37 + row * .48, 11.6, .43, 18, "EEF3F6")
        rule = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(.68), Inches(6.68), Inches(11.95), Inches(.012))
        rule.fill.solid()
        rule.fill.fore_color.rgb = RGBColor.from_string("354656")
        rule.line.fill.background()
        text_box(slide, item["note"], .68, 6.86, 10.8, .35, 10, "BDCBD5")
        text_box(slide, f"{index:02d} / {len(SLIDES):02d}", 11.88, 6.86, .8, .35, 10, "9AD7B7", True)
        slide.notes_slide.notes_text_frame.text = item["speaker"]
    presentation.save(ROOT / "docs/DEMO_SLIDES.pptx")


if __name__ == "__main__":
    build_html()
    build_powerpoint()
    print(f"Built {len(SLIDES)} slides: docs/DEMO_SLIDES.html and docs/DEMO_SLIDES.pptx")
