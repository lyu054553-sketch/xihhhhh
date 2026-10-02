"""Build v0.3 HTML and editable PowerPoint from one source. Requires python-pptx."""

from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SLIDES = [
    {
        "eyebrow": "HUO BU YA QIAN / CONTRACT v0.3",
        "title": "货不压钱\n让库存建议有据可查",
        "subtitle": "五个业务入口，一份零售通用契约，使用虚构零食数据演示。",
        "points": [
            "范围与参数形成统一请求",
            "结果、证据、告警由服务返回",
            "情景先确认，建议只记录模拟决策"
        ],
        "note": "当前为前端契约交付 · 真实 v0.3 后端与模型尚未联调",
        "speaker": "货不压钱关注连锁零售中的库存成本占用和预计采购支出。本轮交付是依照魏的 v0.3 唯一契约整理的前端、合成数据和测试。演示录像明确使用接口夹具，不把它称为真实模型或后端计算结果。"
    },
    {
        "eyebrow": "01 / FIVE AGENTS",
        "title": "五个业务入口\n共用事实与返回结构",
        "subtitle": "门店、商品、库存、销量、采购、批次和经营规则保持通用模型。",
        "points": [
            "滞销诊断：低动销、高占款及证据",
            "跨店调拨：两店库存、数量及约束",
            "近效期：预测窗口、批次与成本风险",
            "采购刹车：可调整采购量及缺货风险",
            "资金周转模拟：基线、方案、假设与风险"
        ],
        "note": "门店、SKU、供应商与交易数据均为合成；不对应真实连锁企业",
        "speaker": "五个入口通过同一运行接口提交分析范围、参数和版本。前端不重复实现五套业务计算，也不会把参考预期作为页面结果。金额和约束由魏的工具层计算，模型负责理解、组织与解释。"
    },
    {
        "eyebrow": "02 / CONTRACT",
        "title": "统一运行\n统一呈现结果",
        "subtitle": "POST /api/v1/agent-runs",
        "points": [
            "请求：request_id、scope、params、数据与规则版本",
            "响应：run_id、状态、步骤、证据和建议",
            "收到响应后才展示实际返回步骤",
            "空值保持未知，空结果保持空",
            "关联信息或结构不符时阻止使用结果"
        ],
        "note": "现有 main 旧后端尚无统一路由；前端不会调用旧工作台伪装兼容",
        "speaker": "现在可以独立启动前端、查看输入包。没有配置 v0.3 服务时，运行会明确报 API_NOT_CONFIGURED。浏览器测试只验证给定契约响应下的界面行为，真实后端上线后还要重新联调。"
    },
    {
        "eyebrow": "03 / CONFIRMATION",
        "title": "先核对情景\n再开始模拟",
        "subtitle": "描述调整 → preview → 人工核对 → simulate → 模拟决策。",
        "points": [
            "预览只有结构化调整与假设，items 为空",
            "确认后复用 session_id 和 scenario_id",
            "confirmed=true 只允许开始计算",
            "修改输入使旧情景与旧结果失效",
            "建议确认需返回 recorded / simulation"
        ],
        "note": "情景确认与建议确认均不修改真实库存、采购单或收银数据",
        "speaker": "以城西店每日坚果 PO-003 少采购六袋为输入例子。先核对后端返回的门店、商品、采购单、数量和周期。预览没有模拟结果金额；点击确认后才计算。之后的模拟确认只记录演示决策。"
    },
    {
        "eyebrow": "04 / MONEY AND RISK",
        "title": "分清金额含义\n同时解释风险",
        "subtitle": "传输采用整数分，页面只换算显示，不自行生成业务数字。",
        "points": [
            "库存成本占用不等于银行账户余额",
            "采购减量表示预计避免未来采购承诺",
            "内部调拨不直接降低全链路库存总额",
            "近效期金额是成本风险敞口估算",
            "没有后续补货时，两种采购方案都可能缺货"
        ],
        "note": "模拟必须展示基线、方案、时间口径、假设与缺货风险",
        "speaker": "这里不声称客户已经获得收益。三十天模拟如果不安排后续补货，基线和减量方案都可能断货。只展示减少采购金额会误导决策，所以必须连同库存资金曲线、缺货风险和计算时点解释。"
    },
    {
        "eyebrow": "05 / FAILURE STATES",
        "title": "错误可以核对\n旧结果不能继续使用",
        "subtitle": "失败处理进入统一请求与页面状态，不由临时替代数据掩盖。",
        "points": [
            "no_data：清晰空状态；needs_input：补充缺项",
            "partial：已有结果与告警同时保留",
            "超时、网络和非法响应明确报错",
            "快速切换时，旧响应不覆盖当前输入",
            "取消等待不等于撤销服务端运行"
        ],
        "note": "夹具中的 AI_TIMEOUT 等是故障注入，不证明真实模型已完成故障测试",
        "speaker": "失败演示可以检查页面是否保留上下文、是否阻止错误决策。开发代理不自动重试写入。真实模型超时和恢复需要在魏的服务接入后单独验收，不能用浏览器夹具的通过数量代替。"
    },
    {
        "eyebrow": "06 / REPRODUCIBILITY",
        "title": "输入可复现\n验证边界可说明",
        "subtitle": "snack-demo-v1 · snack-policy-v1 · 固定种子与文件校验值。",
        "points": [
            "七类共享模型提供 CSV 与完整 JSON 输入包",
            "参考场景和预期独立保存，不注入在线结果",
            "公开静态资源白名单与两个 POST 透明转发",
            "浏览器夹具验证界面，传输夹具验证代理",
            "实测 Node 52 项、Python 前端相关 46 项通过"
        ],
        "note": "另有 39 项旧后端回归；夹具验证不证明真实 v0.3 后端通过",
        "speaker": "朱交付前端、合成场景、测试和演示。启动前端只需要 Python 标准库，不启动旧数据库或业务后端。录像展示真实浏览器操作，但响应来自显式测试夹具，因此它只能证明前端交互。"
    },
    {
        "eyebrow": "07 / INTEGRATION",
        "title": "下一步\n接入魏的真实 v0.3 服务",
        "subtitle": "先跑通滞销样例，再验证五个 Agent、会话模拟和错误恢复。",
        "points": [
            "实现两条路由并加载约定的数据与规则版本",
            "确认库存资金时点与日内到货顺序",
            "确认效期预测日期和 FEFO 分配",
            "确认采购箱规与后续补货假设",
            "实测模型、工具、证据、并发与模拟决策"
        ],
        "note": "GitHub / lyu054553-sketch/xihhhhh · 朱的开发分支 zmj",
        "speaker": "库存资金的取值时点、到货与销售先后、到期日能否销售，以及箱规和后续补货尚需双方冻结。本次不替魏实现后端，也不从前端补算这些数字。联调通过后再发布真实服务演示与模型评测结果。"
    }
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
<title>货不压钱 · 演示稿</title><style>
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
function show(index){current=Math.max(0,Math.min(slides.length-1,index));slides.forEach((slide,i)=>{slide.hidden=i!==current});document.querySelector('#position').textContent=`${current+1} / ${slides.length}`;document.querySelector('#previous').disabled=current===0;document.querySelector('#next').disabled=current===slides.length-1;document.title=`${current+1}/${slides.length} · 货不压钱演示稿`;}
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
    presentation.core_properties.title = "货不压钱 · v0.3 契约演示"
    presentation.core_properties.subject = "v0.3 / 合成零食数据 / 朱的前端交付 / zmj"
    presentation.core_properties.author = "货不压钱项目组"
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
