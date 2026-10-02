from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import landscape, A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "pdf" / "资金活水-Agent-产品介绍.pdf"
TMP = ROOT / "tmp" / "pdfs"
TMP.mkdir(parents=True, exist_ok=True)
OUT.parent.mkdir(parents=True, exist_ok=True)

FONT_PATH = "/System/Library/Fonts/STHeiti Medium.ttc"
pdfmetrics.registerFont(TTFont("CN", FONT_PATH, subfontIndex=0))
FONT = "CN"

W, H = landscape(A4)
M = 38

NAVY = HexColor("#10233F")
BLUE = HexColor("#1D75E8")
TEAL = HexColor("#21B8A5")
PURPLE = HexColor("#7864EF")
ORANGE = HexColor("#F2A51D")
RED = HexColor("#EB6670")
INK = HexColor("#263A56")
MUTED = HexColor("#6C7E98")
PALE = HexColor("#F4F8FD")
LINE = HexColor("#D8E4F2")
WHITE = colors.white

BRAND_MARK = ROOT / "assets" / "brand-mark.png"
IMG_DIR = Path(os.environ.get("INVENTORY_PDF_SCREENSHOTS", ROOT / "design-assets" / "screenshots"))

SCREENSHOTS = [
    IMG_DIR / "codex-clipboard-b5eca0e3-31d6-495d-81ae-d7f276790142.png",
    IMG_DIR / "codex-clipboard-a6b0773b-10e9-4f78-b11a-639ae38865d4.png",
    IMG_DIR / "codex-clipboard-cc5928c0-7016-4b2e-940c-88cfb7addee2.png",
    IMG_DIR / "codex-clipboard-d189dc0a-2e59-4140-bc3a-b3e6efe83b2f.png",
    IMG_DIR / "codex-clipboard-2aa29296-a7bd-457d-aec6-fa883171e667.png",
    IMG_DIR / "codex-clipboard-0d2c73e1-16aa-439b-863d-972bad9f1755.png",
    IMG_DIR / "codex-clipboard-124adf77-b813-439d-8176-56f2bbfd1a39.png",
    IMG_DIR / "codex-clipboard-a248d485-7579-4cc5-a093-5fa3ebf62a68.png",
    IMG_DIR / "codex-clipboard-43146029-efd9-40bf-9e03-da9734290850.png",
]


def text_width(text: str, size: float) -> float:
    return pdfmetrics.stringWidth(text, FONT, size)


def wrap_text(text: str, size: float, max_width: float) -> List[str]:
    lines: List[str] = []
    for para in text.split("\n"):
        current = ""
        for ch in para:
            candidate = current + ch
            if current and text_width(candidate, size) > max_width:
                lines.append(current)
                current = ch
            else:
                current = candidate
        if current:
            lines.append(current)
        elif not lines or lines[-1] != "":
            lines.append("")
    return lines


def draw_text(c: canvas.Canvas, x: float, y: float, text: str, size: float,
              color=INK, max_width: float | None = None, leading: float | None = None,
              max_lines: int | None = None) -> float:
    c.setFont(FONT, size)
    c.setFillColor(color)
    leading = leading or size * 1.55
    lines = wrap_text(text, size, max_width) if max_width else text.split("\n")
    if max_lines:
        lines = lines[:max_lines]
    for line in lines:
        c.drawString(x, y, line)
        y -= leading
    return y


def draw_centered(c: canvas.Canvas, x: float, y: float, text: str, size: float, color=INK) -> None:
    c.setFont(FONT, size)
    c.setFillColor(color)
    c.drawCentredString(x, y, text)


def rounded_card(c: canvas.Canvas, x: float, y: float, w: float, h: float,
                 fill=WHITE, stroke=LINE, radius=14, line_width=0.8) -> None:
    c.setFillColor(fill)
    c.setStrokeColor(stroke)
    c.setLineWidth(line_width)
    c.roundRect(x, y, w, h, radius, fill=1, stroke=1)


def pill(c: canvas.Canvas, x: float, y: float, text: str, fill=BLUE, fg=WHITE, size=8.5) -> None:
    w = text_width(text, size) + 18
    c.setFillColor(fill)
    c.roundRect(x, y - 3, w, 18, 9, fill=1, stroke=0)
    c.setFillColor(fg)
    c.setFont(FONT, size)
    c.drawString(x + 9, y + 2, text)


def header(c: canvas.Canvas, section: str, number: str, accent=BLUE) -> None:
    c.setFillColor(PALE)
    c.rect(0, 0, W, H, fill=1, stroke=0)
    c.setFillColor(accent)
    c.rect(M, H - 30, 42, 4, fill=1, stroke=0)
    c.setFillColor(MUTED)
    c.setFont(FONT, 8.5)
    c.drawString(M, H - 48, section)
    c.drawRightString(W - M, H - 48, number)
    c.setFillColor(LINE)
    c.setLineWidth(0.6)
    c.line(M, 34, W - M, 34)
    c.setFillColor(MUTED)
    c.setFont(FONT, 8)
    c.drawString(M, 20, "资金活水 Agent  |  多门店库存与现金流智能经营系统")
    c.drawRightString(W - M, 20, "产品介绍 / 2026")


def title_block(c: canvas.Canvas, eyebrow: str, title: str, subtitle: str, accent=BLUE) -> None:
    pill(c, M, H - 82, eyebrow, fill=accent)
    draw_text(c, M, H - 116, title, 25, NAVY, max_width=W - 2 * M)
    draw_text(c, M, H - 143, subtitle, 10.5, MUTED, max_width=W - 2 * M, leading=16)


def screenshot_card(c: canvas.Canvas, path: Path, x: float, y: float, w: float, h: float) -> None:
    rounded_card(c, x - 7, y - 7, w + 14, h + 14, fill=WHITE, stroke=LINE, radius=14)
    c.drawImage(ImageReader(str(path)), x, y, width=w, height=h, preserveAspectRatio=True, anchor="c", mask="auto")


def bullets(c: canvas.Canvas, x: float, y: float, items: Sequence[Tuple[str, str]], width: float,
           accent=BLUE, size=9.5, leading=17) -> float:
    for label, body in items:
        c.setFillColor(accent)
        c.circle(x + 4, y + 3, 3.2, fill=1, stroke=0)
        c.setFillColor(NAVY)
        c.setFont(FONT, size)
        c.drawString(x + 15, y, label)
        y -= leading
        y = draw_text(c, x + 15, y, body, size - 0.6, MUTED, max_width=width - 15, leading=14)
        y -= 8
    return y


def metric(c: canvas.Canvas, x: float, y: float, w: float, value: str, label: str, accent=BLUE) -> None:
    rounded_card(c, x, y, w, 66, fill=WHITE, stroke=LINE, radius=12)
    c.setFillColor(accent)
    c.rect(x, y + 58, w, 8, fill=1, stroke=0)
    c.setFillColor(NAVY)
    c.setFont(FONT, 17)
    c.drawString(x + 14, y + 30, value)
    c.setFillColor(MUTED)
    c.setFont(FONT, 8.5)
    c.drawString(x + 14, y + 14, label)


def page_cover(c: canvas.Canvas) -> None:
    c.setFillColor(PALE)
    c.rect(0, 0, W, H, fill=1, stroke=0)
    c.setFillColor(HexColor("#E6F1FF"))
    c.circle(W - 110, H - 70, 190, fill=1, stroke=0)
    c.setFillColor(HexColor("#DDF7F3"))
    c.circle(W - 210, 70, 130, fill=1, stroke=0)
    c.setFillColor(BLUE)
    c.rect(M, H - 35, 52, 5, fill=1, stroke=0)
    if BRAND_MARK.exists():
        c.drawImage(ImageReader(str(BRAND_MARK)), M, H - 122, width=58, height=58, mask="auto")
    c.setFillColor(NAVY)
    c.setFont(FONT, 33)
    c.drawString(M, H - 172, "资金活水 Agent")
    c.setFillColor(BLUE)
    c.setFont(FONT, 14)
    c.drawString(M, H - 198, "让库存流动起来，让现金活起来")
    draw_text(c, M, H - 250,
              "面向多门店企业的库存与现金流智能经营系统\n把分散在门店里的库存，转化为可识别、可决策、可执行的经营动作。",
              14, INK, max_width=470, leading=24)

    rounded_card(c, M, 88, 360, 112, fill=WHITE, stroke=LINE, radius=16)
    pill(c, M + 20, 174, "核心命题", fill=TEAL)
    draw_text(c, M + 20, 150, "库存不是静态成本，而是等待被重新分配的现金。", 15, NAVY, max_width=315, leading=23)
    draw_text(c, M + 20, 108, "Inventory  →  Insight  →  Action  →  Cash flow", 9.5, MUTED, max_width=315)

    c.setFillColor(NAVY)
    c.setFont(FONT, 9)
    c.drawRightString(W - M, 45, "Product story deck  /  Hackathon edition")


def page_problem(c: canvas.Canvas) -> None:
    header(c, "01 / WHY", "02", TEAL)
    title_block(c, "经营问题", "库存分散，现金被占用，行动难以及时发生", "多门店企业真正缺的不是数据，而是从数据到动作之间的确定性。", TEAL)
    left = M
    top = H - 260
    card_w = 235
    card_h = 112
    problems = [
        ("缺货与积压并存", "同一企业里，有的门店缺货，有的门店库存覆盖天数过高。", RED),
        ("现金沉淀在库存里", "库存成本持续增长，但负责人很难快速判断哪些库存最值得处置。", ORANGE),
        ("数据很全，动作很慢", "调拨、促销、采购和退供往往分散在不同流程，无法形成闭环。", PURPLE),
    ]
    for i, (t, b, col) in enumerate(problems):
        x = left + (i % 3) * (card_w + 16)
        y = top - (i // 3) * 132
        rounded_card(c, x, y, card_w, card_h, fill=WHITE, stroke=LINE, radius=14)
        c.setFillColor(col)
        c.circle(x + 24, y + 82, 9, fill=1, stroke=0)
        draw_text(c, x + 42, y + 83, t, 12, NAVY, max_width=card_w - 56)
        draw_text(c, x + 20, y + 53, b, 9.5, MUTED, max_width=card_w - 40, leading=15)

    rounded_card(c, M, 80, W - 2 * M, 118, fill=HexColor("#EAF4FF"), stroke=HexColor("#BBD9FB"), radius=16)
    draw_text(c, M + 22, 166, "资金活水 Agent 的回答", 14, BLUE, max_width=300)
    draw_text(c, M + 22, 135, "让库存更快流向需要它的地方，让沉淀在库存中的资金重新流动起来，\n让企业在不确定的市场环境中，多一份现金流的安全感，多一份持续增长的机会。", 13, NAVY, max_width=430, leading=21)
    # Flow strip
    flow = [("数据接入", BLUE), ("风险识别", TEAL), ("方案生成", PURPLE), ("审批执行", ORANGE), ("结果复盘", RED)]
    fx = W - M - 292
    for i, (label, col) in enumerate(flow):
        xx = fx + i * 59
        c.setFillColor(col)
        c.circle(xx, 132, 10, fill=1, stroke=0)
        draw_centered(c, xx, 110, label, 8.3, MUTED)
        if i < len(flow) - 1:
            c.setStrokeColor(LINE)
            c.setLineWidth(1.3)
            c.line(xx + 12, 132, xx + 47, 132)


def page_screenshot(c: canvas.Canvas, number: str, section: str, title: str, subtitle: str,
                    path: Path, accent, metrics: Sequence[Tuple[str, str]],
                    items: Sequence[Tuple[str, str]], quote: str) -> None:
    header(c, section, number, accent)
    title_block(c, section, title, subtitle, accent)
    img_x, img_y, img_w, img_h = M, 163, 488, 267
    screenshot_card(c, path, img_x, img_y, img_w, img_h)
    panel_x = 552
    panel_w = W - panel_x - M
    rounded_card(c, panel_x, 163, panel_w, 267, fill=WHITE, stroke=LINE, radius=14)
    c.setFillColor(accent)
    c.rect(panel_x, 407, panel_w, 23, fill=1, stroke=0)
    c.setFillColor(WHITE)
    c.setFont(FONT, 9)
    c.drawString(panel_x + 14, 414, "页面解读")
    y = 387
    y = draw_text(c, panel_x + 14, y, quote, 11.5, NAVY, max_width=panel_w - 28, leading=18)
    y -= 12
    y = bullets(c, panel_x + 14, y, items, panel_w - 28, accent=accent, size=8.8, leading=15)
    # bottom metric rail
    mx = M
    gap = 12
    mw = (W - 2 * M - gap * (len(metrics) - 1)) / len(metrics)
    for value, label in metrics:
        metric(c, mx, 68, mw, value, label, accent)
        mx += mw + gap


def page_architecture(c: canvas.Canvas) -> None:
    header(c, "10 / SYSTEM", "12", PURPLE)
    title_block(c, "系统闭环", "五个业务 Agent，共同把经营判断变成经营动作", "每个 Agent 负责一个高价值场景，所有结果最终汇聚到今日工作台，形成可追踪的执行闭环。", PURPLE)
    agents = [
        ("库存诊断 Agent", "识别库存占用、覆盖天数和积压原因", BLUE),
        ("跨店调拨 Agent", "计算调出、调入、数量与最优路径", TEAL),
        ("近效期处置 Agent", "判断调拨、促销、退供与预计损失", ORANGE),
        ("采购调整 Agent", "联动在途订单，避免重复采购", RED),
        ("现金流模拟 Agent", "比较不同动作对现金释放的影响", PURPLE),
    ]
    x0, y0 = M, 260
    for i, (name, desc, col) in enumerate(agents):
        x = x0 + (i % 3) * 255
        y = y0 - (i // 3) * 130
        rounded_card(c, x, y, 230, 100, fill=WHITE, stroke=LINE, radius=14)
        c.setFillColor(col)
        c.circle(x + 24, y + 73, 10, fill=1, stroke=0)
        draw_text(c, x + 45, y + 77, name, 11, NAVY, max_width=170)
        draw_text(c, x + 20, y + 45, desc, 9, MUTED, max_width=190, leading=14)
    rounded_card(c, M, 75, W - 2 * M, 92, fill=HexColor("#EEF0FF"), stroke=HexColor("#CFCBFF"), radius=16)
    draw_text(c, M + 22, 140, "闭环结果", 13, PURPLE, max_width=100)
    draw_text(c, M + 22, 113, "数据导入  →  风险识别  →  方案生成  →  人工确认  →  执行跟踪  →  结果复盘", 13, NAVY, max_width=700, leading=21)
    draw_text(c, M + 22, 86, "系统不替管理者做最终决策，但会把决策所需的证据、约束和预期影响放在同一个页面里。", 9.5, MUTED, max_width=690)


def page_closing(c: canvas.Canvas) -> None:
    c.setFillColor(NAVY)
    c.rect(0, 0, W, H, fill=1, stroke=0)
    c.setFillColor(HexColor("#214A7D"))
    c.circle(W - 120, H - 100, 190, fill=1, stroke=0)
    c.setFillColor(HexColor("#17365E"))
    c.circle(90, 80, 150, fill=1, stroke=0)
    c.setFillColor(BLUE)
    c.rect(M, H - 45, 50, 5, fill=1, stroke=0)
    c.setFillColor(WHITE)
    c.setFont(FONT, 13)
    c.drawString(M, H - 94, "资金活水 Agent")
    c.setFont(FONT, 30)
    c.drawString(M, H - 150, "让库存流动起来")
    c.setFillColor(HexColor("#71D9C9"))
    c.drawString(M, H - 190, "让资金活起来")
    draw_text(c, M, H - 250, "让每一个经营动作都有依据，\n让每一次库存变化都更接近增长。", 16, WHITE, max_width=400, leading=28)
    rounded_card(c, M, 82, 350, 106, fill=HexColor("#1A3962"), stroke=HexColor("#355C8A"), radius=16)
    draw_text(c, M + 20, 157, "适用企业", 10, HexColor("#9CC5F2"), max_width=200)
    draw_text(c, M + 20, 130, "连锁零售 / 商超 / 便利店 / 母婴 / 服装 / 3C / 餐饮 / 汽配", 11, WHITE, max_width=300, leading=19)
    c.setFillColor(HexColor("#9CC5F2"))
    c.setFont(FONT, 9)
    c.drawString(M, 34, "Hackathon product introduction")
    c.drawRightString(W - M, 34, "Thank you")


def build() -> None:
    missing = [str(p) for p in SCREENSHOTS if not p.exists()]
    if missing:
        raise FileNotFoundError("Missing screenshots: " + ", ".join(missing))
    c = canvas.Canvas(str(OUT), pagesize=(W, H), pageCompression=1)
    c.setTitle("资金活水 Agent - 产品介绍")
    c.setAuthor("资金活水 Agent")

    page_cover(c); c.showPage()
    page_problem(c); c.showPage()
    page_screenshot(c, "03", "02 / OVERVIEW", "经营总览：先看资金沉淀，再找优先动作", "一屏掌握企业整体库存规模、覆盖范围、风险信号与 Agent 运行状态。", SCREENSHOTS[0], BLUE,
                    [("¥202.4万", "当前库存成本"), ("50 家", "经营门店"), ("2.7%", "待优先处置库存")],
                    [("八项关键指标", "回答资金沉淀、经营覆盖和风险动作三个问题。"), ("Top 门店定位", "按库存成本排序，点击柱子即可筛选下方门店明细。"), ("风险入口", "将近效期、建议调拨和预计滞销集中为可行动信号。"), ("Agent 状态", "实时展示各个 Agent 与后端服务是否正常运行。")],
                    "先用一张经营总览，把企业库存从‘一堆数字’变成‘一组优先级’。")
    c.showPage()
    page_screenshot(c, "04", "03 / WORKBENCH", "今日工作台：把分析结果变成今天要处理的事", "任务按照紧急程度和建议处理时间排序，管理者从待办开始，而不是从报表开始。", SCREENSHOTS[1], TEAL,
                    [("13 项", "待处理任务"), ("¥55,622", "待处理库存成本"), ("4 步", "从核对到确认结果")],
                    [("任务聚合", "把诊断、调拨、近效期和采购调整统一汇入一张工作台。"), ("证据优先", "每个任务都能回看库存、销量、覆盖天数和计算依据。"), ("执行闭环", "确认方案后进入审批、门店执行与结果确认。"), ("面向负责人", "把复杂分析压缩成清晰的下一步动作。")],
                    "系统不只是告诉负责人哪里有问题，还会告诉他今天应该先处理什么。")
    c.showPage()
    page_screenshot(c, "05", "04 / DIAGNOSIS AGENT", "滞销库存诊断：解释为什么卖不动", "诊断 Agent 不只识别慢销商品，还会追溯形成原因，并给出后续处理方向。", SCREENSHOTS[2], BLUE,
                    [("12 个", "待诊断商品"), ("¥51,772", "关注库存成本"), ("168 天", "示例覆盖天数")],
                    [("多维判断", "结合近 30 天销量、库存成本与覆盖天数，识别高风险商品。"), ("原因核查", "进一步判断需求不足、陈列问题、区域不匹配或采购过量。"), ("报告可追溯", "点击查看报告，回看诊断证据和建议动作。"), ("动作建议", "在调拨、促销、暂停采购与继续观察之间做出选择。")],
                    "它解决的不是‘哪些商品卖得慢’，而是‘为什么卖得慢，以及怎么让库存重新流动起来’。")
    c.showPage()
    page_screenshot(c, "06", "05 / TRANSFER AGENT", "跨门店智能调拨：把合适的货送到合适的门店", "系统在不增加缺货风险的前提下，综合安全库存、需求、距离和配送成本生成调拨方案。", SCREENSHOTS[3], TEAL,
                    [("40 件", "建议调拨数量"), ("¥3,200", "本次调拨库存成本"), ("¥3,120", "预计避免损失")],
                    [("从哪里调", "从西湖文三店调出 40 件，调拨后仍保留安全库存。"), ("调到哪里", "优先匹配余杭未来店，也可横向比较其他接收门店。"), ("怎么走最优", "综合距离、配送费用、可接收数量和预计到店时间。"), ("影响可量化", "展示调拨前后库存变化，以及未来 73 天的经营影响。")],
                    "跨店调拨 Agent 把‘哪里库存高、哪里需要货’，变成‘调多少、调到哪里、能减少多少损失’。")
    c.showPage()
    page_screenshot(c, "07", "06 / EXPIRY AGENT", "近效期商品现金抢救：在损失发生前争取时间", "系统按剩余有效期与销售速度排序，帮助企业优先处理最容易形成损失的批次。", SCREENSHOTS[4], ORANGE,
                    [("7 批", "待抢救批次"), ("¥21,568", "近效期库存成本"), ("14 天", "示例剩余可售时间")],
                    [("批次倒计时", "把每个门店、商品和批次放在同一张处置队列中。"), ("可售预测", "比较库存数量与预计正常销售量，估算不处置会剩余多少。"), ("分级处理", "根据剩余天数给出紧急处理或本周处理建议。"), ("处置方案", "推荐调拨、促销、退供的组合动作，并估算潜在损失。")],
                    "近效期处置 Agent 的价值，是在商品变成损失之前，帮企业抢回可行动的时间。")
    c.showPage()
    page_screenshot(c, "08", "07 / PROCUREMENT AGENT", "采购刹车：先核对在途订单，再决定是否继续补货", "采购调整 Agent 将当前库存、在途数量、未执行采购和销售速度放在一起判断。", SCREENSHOTS[5], RED,
                    [("2 个", "采购调整口"), ("¥7,756", "相关库存成本"), ("180 件", "不调整的预计库存")],
                    [("不是直接停单", "系统先核对采购单状态、到货时间和当前库存。"), ("识别重复风险", "区分已经在途、尚未采购和确实需要补充的数量。"), ("动作可编辑", "支持减量、取消未执行量或协商延期付款。"), ("约束透明", "把安全库存、销量预测和供应商确认纳入判断边界。")],
                    "采购刹车不是简单地少买，而是避免新的库存继续占用现金。")
    c.showPage()
    page_screenshot(c, "09", "08 / CASH SIMULATION", "现金流情景模拟：先看未来，再决定今天怎么做", "管理者可以用自然语言输入目标与约束，让 Agent 对可计算的现金事件进行推演。", SCREENSHOTS[6], PURPLE,
                    [("30 天", "示例时间范围"), ("¥20 万", "目标释放现金"), ("可解释", "每个结果都有数据边界")],
                    [("目标输入", "例如：30 天内释放 20 万元现金，不要降价。"), ("业务约束", "补充‘乙店不接收’等真实经营限制，避免纸面最优。"), ("方案推演", "Agent 根据当前数据计算现金释放、动作顺序和未满足缺口。"), ("决策前置", "让管理者看到不同动作对库存与现金的影响再确认方案。")],
                    "它把‘我要释放多少现金’这样的经营目标，翻译成可以讨论、可以验证的动作方案。")
    c.showPage()
    page_screenshot(c, "10", "09 / CASE LIBRARY", "案例库：把一次成功处理，变成可以复用的经验", "案例库沉淀跨店调拨、近效期处置、采购调整和陈列改善等真实经营方法。", SCREENSHOTS[7], BLUE,
                    [("12 个", "成功案例"), ("6 类", "经营场景"), ("可复用", "方案经验")],
                    [("按场景浏览", "用跨店调拨、近效期处置、采购调整等标签快速定位相似问题。"), ("结果先行", "每个案例都展示处理数量、周期、金额和关键结果。"), ("适用边界", "明确哪些门店、商品和经营条件适合复用。"), ("经验回流", "让一次成功动作成为下一家门店的决策参考。")],
                    "案例库让系统不仅能回答‘现在怎么办’，还能告诉企业‘过去什么方法有效’。")
    c.showPage()
    page_screenshot(c, "11", "10 / DATA CENTER", "数据中心：让每一次分析都有可追溯的数据入口", "通过库存、销售、采购、批次和门店基础数据，完成导入、识别、校验与分析。", SCREENSHOTS[8], TEAL,
                    [("5 类", "数据模板"), ("4 步", "导入流程"), ("可追溯", "历史分析记录")],
                    [("统一导入", "支持库存、销售、采购/入库、批次/效期和门店基础信息。"), ("字段校验", "系统识别字段并提示缺失、格式和映射问题。"), ("分析留痕", "每次分析都保留销售期间、库存时点、覆盖门店和文件记录。"), ("数据边界", "明确数据只用于本系统分析，不会悄悄同步到其他系统。")],
                    "数据中心是整个系统的地基：只有数据可追溯，后面的诊断和方案才值得被信任。")
    c.showPage()
    page_architecture(c); c.showPage()
    page_closing(c)
    c.save()
    print(OUT)


if __name__ == "__main__":
    build()
