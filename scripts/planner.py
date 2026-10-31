#!/usr/bin/env python3
"""Deterministic single-projector calculator and fixed SVG generator. Python 3.10+."""
import argparse
import datetime
import html
import json
import math
import re
import unicodedata
from pathlib import Path
from string import Template

ROOT = Path(__file__).resolve().parents[1]
PRESETS = {"Full HD": (1920,1080), "WUXGA": (1920,1200), "4K UHD": (3840,2160)}
ALLOWED = {"project","version","date","width","height","distance","position","throw_ratio","lens","aspect","resolution","content_aspect","fit","geometry","notes"}

class InputError(ValueError): pass

def positive(v, name):
    if isinstance(v, bool): raise InputError(f"{name} 必須是正數")
    try: v = float(v)
    except (ValueError, TypeError, OverflowError): raise InputError(f"{name} 必須是正數")
    if not math.isfinite(v) or v <= 0: raise InputError(f"{name} 必須是有限正數")
    return v

def length(v):
    if not isinstance(v, str): raise InputError("長度須包含單位，例如 6m、600公分")
    m = re.fullmatch(r"\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*(m|cm|mm|公尺|公分|毫米)\s*", v)
    if not m: raise InputError(f"不支援的長度：{v}")
    x = positive(m[1], "長度") * {"m":1,"cm":.01,"mm":.001,"公尺":1,"公分":.01,"毫米":.001}[m[2]]
    if not math.isfinite(x) or x <= 0: raise InputError("長度換算超出範圍")
    return x

def ratio(v):
    if not isinstance(v,str): raise InputError("比例須為 寬:高")
    parts = v.split(":")
    if len(parts)!=2: raise InputError("比例須為 寬:高")
    a,b = (positive(s,"長寬比") for s in parts)
    r = a/b
    if not .1 <= r <= 10: raise InputError("長寬比超出第一版支援範圍 0.1–10")
    return r

def close(a,b): return math.isclose(a,b,rel_tol=1e-6,abs_tol=1e-9)
def fmt(v): return f"{v:.3e}" if v and (abs(v)<.0001 or abs(v)>=1e6) else f"{v:.4f}".rstrip("0").rstrip(".")

def calculate(data):
    if not isinstance(data,dict): raise InputError("輸入須為 JSON 物件")
    unknown = set(data)-ALLOWED
    if unknown: raise InputError("未知欄位："+", ".join(sorted(unknown)))
    for key in ("project","version","date"):
        if not isinstance(data.get(key),str) or not data[key].strip(): raise InputError(f"缺少 {key}")
        if any(ord(c)<32 for c in data[key]): raise InputError(f"{key} 不允許控制字元")
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}",data["date"]): raise ValueError()
        datetime.date.fromisoformat(data["date"])
    except ValueError: raise InputError("日期須為 YYYY-MM-DD")
    if data.get("geometry","standard") != "standard": raise InputError("僅支援一般正投、平面正對幕面；UST／反射／傾斜不支援")
    notes = data.get("notes",[])
    if not isinstance(notes,list) or any(not isinstance(x,str) or any(ord(c)<32 for c in x) for x in notes): raise InputError("notes 須為不含控制字元的文字陣列")
    res = data.get("resolution")
    if isinstance(res,str):
        if res not in PRESETS: raise InputError("未知解析度名稱")
        res = PRESETS[res]
    if not isinstance(res,(list,tuple)) or len(res)!=2 or any(isinstance(x,bool) or not isinstance(x,int) or x<=0 for x in res):
        raise InputError("請提供原生解析度：Full HD、WUXGA、4K UHD 或 [水平像素, 垂直像素]")
    native = res[0]/res[1]
    ar = ratio(data["aspect"]) if "aspect" in data else native
    if not .1<=ar<=10: raise InputError("原生比例超出範圍")
    if not close(native,ar): raise InputError("畫面比例與原生解析度不一致；影片比例請放 content_aspect（本版假設方形像素）")
    w = length(data["width"]) if "width" in data else None
    d = length(data["distance"]) if "distance" in data else None
    t = positive(data["throw_ratio"],"投射比") if "throw_ratio" in data else None
    lens = data.get("lens")
    if lens is not None:
        if not isinstance(lens,list) or len(lens)!=2: raise InputError("lens 須為 [最小投射比, 最大投射比]")
        lens = [positive(v,"鏡頭投射比") for v in lens]
        if lens[0]>lens[1]: raise InputError("鏡頭最小值不可大於最大值")
    if t is not None and not .4<=t<=10 or lens and not (.4<=lens[0]<=lens[1]<=10):
        raise InputError("投射比超出此一般正投模型的保守支援範圍 0.4–10；請核對光學系統與原廠資料")
    if w is None and d is not None and t is not None: w = d/t
    elif d is None and w is not None and t is not None: d = w*t
    elif t is None and w is not None and d is not None: t = d/w
    if w is None or (d is None and lens is None): raise InputError("資料不足：請提供 W+D、W+T、D+T，或 W+鏡頭投射比區間")
    if d is not None and t is not None and not close(d,w*t): raise InputError("寬、距離與投射比互相矛盾（容差 1e-6）")
    if t is not None and not .4<=t<=10: raise InputError("所需投射比超出此一般正投模型支援範圍 0.4–10")
    h=w/ar
    if "height" in data and not close(length(data["height"]),h): raise InputError("提供的高度與畫面比例不一致")
    if any(not math.isfinite(x) or x<=0 for x in [w,h,math.hypot(w,h), w*res[1]/res[0]]): raise InputError("計算溢位或尺寸不合理")
    position = length(data["position"]) if "position" in data else d
    if "position" in data and d is not None and not close(position,d): raise InputError("position 與 distance 不一致；請只指定同一個位置")
    interval = [w*lens[0],w*lens[1]] if lens else None
    if any(not math.isfinite(v) for v in [w,h]+([d] if d else [])+(interval or [])): raise InputError("計算超出有限數值範圍")
    valid = None if interval is None or position is None else interval[0]-1e-9<=position<=interval[1]+1e-9
    warnings=[]
    if valid is False: warnings.append("指定位置不在鏡頭允許距離區間，無法以此鏡頭達成指定寬度。")
    if lens and t is not None and not lens[0]-1e-9<=t<=lens[1]+1e-9: warnings.append("所需投射比超出鏡頭範圍。")
    mode=data.get("fit","contain")
    if mode not in ("contain","cover","stretch"): raise InputError("fit 只支援 contain、cover、stretch")
    cr=ratio(data["content_aspect"]) if "content_aspect" in data else ar
    if mode=="contain":
        cw,ch=(w,w/cr) if cr>=ar else (h*cr,h)
        bars=[(w-cw)/2,(h-ch)/2]; crop=[0,0]
    elif mode=="cover":
        cw,ch=(h*cr,h) if cr>=ar else (w,w/cr)
        bars=[0,0]; crop=[max(0,(cw-w)/2),max(0,(ch-h)/2)]
        warnings.append("使用者選擇等比填滿裁切（cover）；超出幕面的內容會被裁去。")
    else:
        cw,ch=w,h; bars=[0,0];crop=[0,0]
        warnings.append("使用者明確選擇拉伸（stretch），內容可能變形。")
    assumptions=["單台一般正投，平面幕面且鏡頭正對中心；不含鏡頭位移。", "距離由原廠定義的鏡頭參考點量至幕面，不是機身外殼或吊架。", "須核對原廠投射距離定義、鏡頭限制與安裝公差；不捏造機種規格。", "不涵蓋超短焦、反射式光路、傾斜／曲面、多機融合及實機控制。", "不計亮度、對焦景深、梯形校正或寫實渲染；本圖僅概念配置。"]
    if d is None: assumptions.append("未選定固定投射距離；俯視圖使用候選位置示意。" if position is not None else "未指定固定投射位置；俯視圖以鏡頭最小距離示意，並非已選定位置。")
    return dict(project=data["project"],version=data["version"],date=data["date"],width=w,height=h,diagonal_m=math.hypot(w,h),diagonal_in=math.hypot(w,h)/.0254,distance=d,throw_ratio=t,lens=lens,interval=interval,position=position,position_valid=valid,resolution=list(res),aspect=ar,aspect_label=data.get("aspect",f"{res[0]//math.gcd(*res)}:{res[1]//math.gcd(*res)}"),pitch_mm=w/res[0]*1000,fit=mode,content_width=cw,content_height=ch,bars_each_m=bars,crop_each_m=crop,warnings=warnings,assumptions=assumptions,notes=notes)

# Deterministic weighted wrapping, independent of installed fonts. All SVG text is clipped.
def wrap(text, capacity):
    lines=[]; buf=""; used=0
    for c in str(text):
        n=2 if unicodedata.east_asian_width(c) in "WF" else 1
        if used+n>capacity: lines.append(buf);buf="";used=0
        buf+=c;used+=n
    if buf or not lines: lines.append(buf)
    return lines

def text(x,y,value,size=18,anchor="start",color="#243444"):
    return f'<text x="{x}" y="{y}" font-size="{size}" text-anchor="{anchor}" fill="{color}">{html.escape(str(value))}</text>'

def line(x1,y1,x2,y2,dim=False):
    marker=' marker-start="url(#arrow)" marker-end="url(#arrow)"' if dim else ''
    return f'<line x1="{x1:.3f}" y1="{y1:.3f}" x2="{x2:.3f}" y2="{y2:.3f}" stroke="#42657d" stroke-width="2"{marker}/>'

def render(r):
    overflow=[]
    def field(value,capacity,limit):
        ls=wrap(value,capacity)
        if len(ls)>limit:
            overflow.append(str(value)); ls=ls[:limit];ls[-1]=ls[-1][:-2]+"…"
        return ls
    title="".join(text(48,68+i*26,s,26) for i,s in enumerate(field(r["project"],70,2)))
    meta=text(1130,47,field("版本 "+r["version"],42,1)[0],16)+text(1130,71,"日期 "+r["date"],16)+text(1130,95,"單位 m / mm",16)
    w,h=r['width'],r['height']; d=r['distance'] or r['position'] or r['interval'][0]
    scale=min(570/d,390/w); sx,sy=175,435; ex=sx+d*scale; half=w*scale/2
    top=f'<polygon points="{sx},{sy} {ex},{sy-half} {ex},{sy+half}" fill="#e0eef5" stroke="#8babbe" stroke-width="2"/>'
    top+=line(ex,sy-half,ex,sy+half)+f'<circle cx="{sx}" cy="{sy}" r="7" fill="#236b8e"/>'
    top+=f'<rect x="{sx-43}" y="{sy-15}" width="35" height="30" rx="4" fill="#236b8e"/>'
    top+=text(sx-50,sy+60,"鏡頭參考點",16)+text(ex,sy-half-24,"幕面",18,"middle")
    top+=line(sx,700,ex,700,True)+text((sx+ex)/2,685,f"D = {fmt(d)} m"+("（示意）" if r['distance'] is None else ""),18,"middle")
    top+=line(ex+34,sy-half,ex+34,sy+half,True)+text(ex+48,sy,f"W {fmt(w)} m",16)
    top+=text(65,762,f"圖面比例尺：{fmt(scale)} SVG px / m（俯視等比）",16)
    # Separate elevation scale; panel boundaries never move.
    es=min(360/w,150/h); ew,eh=w*es,h*es; cx,cy=1260,285; x,y=cx-ew/2,cy-eh/2
    front=f'<rect x="{x}" y="{y}" width="{ew}" height="{eh}" fill="#243444" stroke="#236b8e" stroke-width="2"/>'
    if r['fit']=="contain":
        aw,ah=r['content_width']*es,r['content_height']*es
        front+=f'<rect x="{cx-aw/2}" y="{cy-ah/2}" width="{aw}" height="{ah}" fill="#71b2c9"/>'
    front+=line(x-20,y,x-20,y+eh,True)
    front+=line(x-20,y,x-20,y+eh,True)
    front+=line(x,385,x+ew,385,True)+text(cx,410,f"W {fmt(w)} m | 比例 {r['aspect_label']}",16,"middle")
    front+=text(1010,195,f"H {fmt(h)} m",16)+text(1010,432,f"比例尺 {fmt(es)} px / m（正視等比）",14)
    rows=[("解析度",f"{r['resolution'][0]} × {r['resolution'][1]}"),("投射比",fmt(r['throw_ratio']) if r['throw_ratio'] else "未選定"),("投射距離",f"{fmt(r['distance'])} m" if r['distance'] else "未選定"),("畫面寬 × 高",f"{fmt(w)} × {fmt(h)} m"),("對角線",f"{fmt(r['diagonal_m'])} m / {fmt(r['diagonal_in'])} in"),("像素間距",f"{fmt(r['pitch_mm'])} mm（方形像素）"),("鏡頭允許距離",'–'.join(fmt(v) for v in r['interval'])+" m" if r['interval'] else "未提供鏡頭範圍"),("指定位置檢查", "不在範圍" if r['position_valid'] is False else ("在範圍" if r['position_valid'] else "未檢查")),("影片有效範圍",f"{fmt(r['content_width'])} × {fmt(r['content_height'])} m"),("顯示方式",r['fit']+"；黑邊／裁切詳見摘要")]
    table=""
    for i,(k,v) in enumerate(rows):
        yy=507+i*27
        table+=text(1010,yy,k,15)+text(1185,yy,v,15,color="#b44b38" if k=="指定位置檢查" and r['position_valid'] is False else "#243444")
    footer=[]
    # Exactly 5 lines on the page, excess content is complete in Markdown attachment.
    all_notes=r['warnings']+r['assumptions']+r['notes']
    for n in all_notes: footer.extend(wrap(n,146))
    visible=footer[:5]
    if len(footer)>5: visible[-1]="其餘假設、限制及完整備註請見同名 Markdown 摘要。"
    foot="".join(text(65,875+i*19,s,16) for i,s in enumerate(visible))
    if overflow: foot+=text(1000,970,"長文字已縮略；全文見 Markdown 附件。",14)
    template=Template((ROOT/'assets/templates/layout.svg').read_text(encoding='utf-8'))
    return template.substitute(title=title,meta=meta,top=top,front=front,table=table,footer=foot)

def markdown(r):
    rows=[("畫面寬",f"{fmt(r['width'])} m"),("畫面高",f"{fmt(r['height'])} m"),("對角線",f"{fmt(r['diagonal_m'])} m / {fmt(r['diagonal_in'])} in"),("像素間距",f"{fmt(r['pitch_mm'])} mm"),("投射距離",f"{fmt(r['distance'])} m" if r['distance'] else "未選定"),("所需投射比",fmt(r['throw_ratio']) if r['throw_ratio'] else "未選定"),("原生解析度",str(r['resolution'])),("鏡頭允許距離",str(r['interval'])+" m" if r['interval'] else "未提供"),("指定位置",str(r['position'])+" m" if r['position'] else "未指定"),("位置檢查",str(r['position_valid'])),("內容顯示",r['fit']),("有效內容寬高",f"{fmt(r['content_width'])} × {fmt(r['content_height'])} m"),("每側黑邊（左右／上下）",str(r['bars_each_m'])+" m"),("每側裁切（左右／上下）",str(r['crop_each_m'])+" m")]
    # HTML escape metadata and table cells so untrusted project strings cannot add markup.
    safe=lambda v:html.escape(str(v)).replace("|","&#124;")
    s=f"# {safe(r['project'])}\n\n版本：{safe(r['version'])}；日期：{r['date']}；模板：PP-1.0\n\n| 項目 | 結果 |\n|---|---|\n"
    s+=''.join(f"| {safe(k)} | {safe(v)} |\n" for k,v in rows)
    s+="\n## 驗算\n\n"
    if r['distance'] is not None: s+=f"D − T×W = {r['distance']-r['throw_ratio']*r['width']:.3g} m\n"
    s+=f"H − W/比例 = {r['height']-r['width']/r['aspect']:.3g} m；像素間距以原生全畫面寬計算。\n\n## 警告、假設與限制\n\n"
    s+=''.join('- '+safe(x)+'\n' for x in r['warnings']+r['assumptions']+r['notes'])
    return s

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input',type=Path);parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    try:
        data=json.loads(args.input.read_text(encoding='utf-8')); r=calculate(data)
        outputs={'.svg':render(r),'.md':markdown(r),'.json':json.dumps(r,ensure_ascii=False,indent=2,allow_nan=False)}
        if any(args.output.with_suffix(ext).exists() for ext in outputs): raise InputError("輸出已存在，請選擇新檔名或版本")
        args.output.parent.mkdir(parents=True,exist_ok=True)
        for ext,content in outputs.items(): args.output.with_suffix(ext).write_text(content,encoding='utf-8')
    except (InputError, OSError, json.JSONDecodeError) as e: parser.exit(2,f"錯誤：{e}\n")
    print(f"完成：{args.output}.svg / .md / .json")
if __name__=='__main__': main()
