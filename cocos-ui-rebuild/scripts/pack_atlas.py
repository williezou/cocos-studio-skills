#!/usr/bin/env python3
"""Pack a Cocos Studio CSI locally into PNG/plist format 2 and verify visible pixels."""
import argparse
import json
import math
import plistlib
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image, ImageChops
from cocos_ui import resolve


def intersects(a,b):
    return a[0] < b[0]+b[2] and b[0] < a[0]+a[2] and a[1] < b[1]+b[3] and b[1] < a[1]+a[3]


def contains(a,b):
    return a[0] <= b[0] and a[1] <= b[1] and a[0]+a[2] >= b[0]+b[2] and a[1]+a[3] >= b[1]+b[3]


def place(free,rect):
    remaining=[]
    x,y,w,h=rect
    for fx,fy,fw,fh in free:
        if not intersects((fx,fy,fw,fh),rect):
            remaining.append((fx,fy,fw,fh))
            continue
        if x > fx:
            remaining.append((fx,fy,x-fx,fh))
        if x+w < fx+fw:
            remaining.append((x+w,fy,fx+fw-x-w,fh))
        if y > fy:
            remaining.append((fx,fy,fw,y-fy))
        if y+h < fy+fh:
            remaining.append((fx,y+h,fw,fy+fh-y-h))
    unique=list(dict.fromkeys(remaining))
    return [r for i,r in enumerate(unique) if not any(i != j and contains(other,r) for j,other in enumerate(unique))]


def pot(value):
    return 1 << max(0,math.ceil(math.log2(max(value,1))))


def extrusion(page,image,x,y,amount=1):
    w,h=image.size
    page.paste(image,(x,y))
    if not amount:
        return
    for source,dest,size in [
        ((0,0,1,h),(x-amount,y),(amount,h)),
        ((w-1,0,w,h),(x+w,y),(amount,h)),
        ((0,0,w,1),(x,y-amount),(w,amount)),
        ((0,h-1,w,h),(x,y+h),(w,amount)),
        ((0,0,1,1),(x-amount,y-amount),(amount,amount)),
        ((w-1,0,w,1),(x+w,y-amount),(amount,amount)),
        ((0,h-1,1,h),(x-amount,y+h),(amount,amount)),
        ((w-1,h-1,w,h),(x+w,y+h),(amount,amount))]:
        page.paste(image.crop(source).resize(size,Image.Resampling.NEAREST),dest)


def visible_equal(a,b):
    if a.size != b.size:
        return False
    if ImageChops.difference(a.getchannel("A"),b.getchannel("A")).getbbox():
        return False
    mask=a.getchannel("A").point(lambda alpha:255 if alpha else 0)
    return all(ImageChops.multiply(ImageChops.difference(x,y),mask).getbbox() is None
               for x,y in zip(a.split()[:3],b.split()[:3]))


def pack(csi,roots,output,force=False):
    csi=Path(csi)
    root=ET.parse(csi).getroot()
    content=root.find("Content")
    if root.tag != "PlistInfoProjectFile" or content is None:
        raise ValueError("不是 CSI 图集描述")
    if content.get("AllowRotation","False") == "True":
        raise ValueError("本地打包器不支持旋转，请使用 Cocos Studio 导出此 CSI")
    maximum=content.find("MaxSize")
    maxw,maxh=int(maximum.get("Width")),int(maximum.get("Height"))
    if min(maxw,maxh) <= 0 or pot(maxw) != maxw or pot(maxh) != maxh:
        raise ValueError("MaxSize 必须为正的 2 的幂")
    padding=int(content.get("PicturePadding",4))
    if padding < 0:
        raise ValueError("PicturePadding 不能为负数")
    border=padding+1
    trim=content.get("AllowTrim","False") == "True"
    entries=[]
    paths=[item.get("Path") for item in content.findall("./ImageFiles/FilePathData")]
    if not paths or len({p.casefold() for p in paths}) != len(paths):
        raise ValueError("图集为空或存在重名/大小写冲突")
    for name in paths:
        with Image.open(resolve(roots,name)) as source:
            original=source.convert("RGBA")
        box=original.getchannel("A").getbbox() if trim else (0,0,*original.size)
        box=box or (0,0,1,1)
        image=original.crop(box)
        if image.width+2*border > maxw or image.height+2*border > maxh:
            raise ValueError(f"单张素材超过图集上限：{name}")
        entries.append(dict(name=name,image=image,original=original,box=box))
    initial=pot(max(max(max(e["image"].size)+2*border for e in entries),
                    math.ceil(math.sqrt(sum((e["image"].width+2*border)*(e["image"].height+2*border) for e in entries)))))
    maxw,maxh=min(maxw,initial),min(maxh,initial)
    entries.sort(key=lambda e:(-max(e["image"].size),-e["image"].width*e["image"].height,e["name"]))
    pages=[]
    for entry in entries:
        w,h=entry["image"].width+2*border,entry["image"].height+2*border
        candidates=[]
        for page_index,page in enumerate(pages):
            for x,y,fw,fh in page["free"]:
                if fw >= w and fh >= h:
                    candidates.append(((min(fw-w,fh-h),max(fw-w,fh-h),page_index,y,x),page_index,x,y))
        if candidates:
            _,page_index,x,y=min(candidates)
        else:
            page_index,x,y=len(pages),0,0
            pages.append(dict(free=[(0,0,maxw,maxh)],entries=[]))
        page=pages[page_index]
        page["free"]=place(page["free"],(x,y,w,h))
        entry["position"]=(x+border,y+border)
        page["entries"].append(entry)
    output=Path(output)
    manifest={"csi":str(csi),"format":2,"trim":trim,"rotated":False,"extrude":1,"pages":[],"frames":{}}
    artifacts=[]
    for page_index,page in enumerate(pages):
        stem=csi.stem if len(pages)==1 else f"{csi.stem}_{page_index}"
        w=pot(max(e["position"][0]+e["image"].width+border for e in page["entries"]))
        h=pot(max(e["position"][1]+e["image"].height+border for e in page["entries"]))
        bitmap=Image.new("RGBA",(w,h))
        frames={}
        for entry in page["entries"]:
            x,y=entry["position"]
            image,original=entry["image"],entry["original"]
            extrusion(bitmap,image,x,y)
            left,top,_,_=entry["box"]
            ox=left+image.width/2-original.width/2
            oy=original.height/2-top-image.height/2
            frames[entry["name"]]=dict(frame=f"{{{{{x},{y}}},{{{image.width},{image.height}}}}}",
                offset=f"{{{ox:g},{oy:g}}}",rotated=False,sourceSize=f"{{{original.width},{original.height}}}")
            manifest["frames"][entry["name"]]=dict(plist=stem+".plist",rect=[x,y,*image.size],source_size=list(original.size))
        data=dict(frames=frames,metadata=dict(format=2,textureFileName=stem+".png",realTextureFileName=stem+".png",size=f"{{{w},{h}}}"))
        artifacts += [(output/(stem+".png"),bitmap),(output/(stem+".plist"),data)]
        manifest["pages"].append(dict(png=stem+".png",plist=stem+".plist",size=[w,h]))
    manifest_path=output/(csi.stem+".atlas.json")
    for path,_ in artifacts+[(manifest_path,manifest)]:
        if path.exists() and not force:
            raise FileExistsError(f"拒绝覆盖已有文件：{path}")
    output.mkdir(parents=True,exist_ok=True)
    for path,value in artifacts:
        if path.suffix == ".png":
            value.save(path)
        else:
            path.write_bytes(plistlib.dumps(value,sort_keys=True))
    manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n")
    for page in manifest["pages"]:
        data=plistlib.loads((output/page["plist"]).read_bytes())
        with Image.open(output/page["png"]) as bitmap:
            bitmap=bitmap.convert("RGBA")
        for name,frame in data["frames"].items():
            x,y,w,h=map(int,re.findall(r"-?\d+",frame["frame"]))
            ox,oy=map(float,re.findall(r"-?\d+(?:\.\d+)?",frame["offset"]))
            ow,oh=map(int,re.findall(r"\d+",frame["sourceSize"]))
            restored=Image.new("RGBA",(ow,oh))
            left,top=round(ow/2+ox-w/2),round(oh/2-oy-h/2)
            restored.paste(bitmap.crop((x,y,x+w,y+h)),(left,top))
            with Image.open(resolve(roots,name)) as source:
                original=source.convert("RGBA")
            if not visible_equal(original,restored):
                raise ValueError(f"图集回读像素不一致：{name}")
    return {"frames":len(entries),"pages":manifest["pages"],"pixel_roundtrip":"passed", "manifest":str(manifest_path)}


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csi",required=True)
    parser.add_argument("--resource-root",required=True,action="append")
    parser.add_argument("--output",required=True)
    parser.add_argument("--force",action="store_true")
    args=parser.parse_args()
    print(json.dumps(pack(args.csi,args.resource_root,args.output,args.force),ensure_ascii=False,indent=2))
