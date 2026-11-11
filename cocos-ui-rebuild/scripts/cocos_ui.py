#!/usr/bin/env python3
"""Cocos Studio source helpers: inventory, CSI, editable CSD, checks and draft rendering."""
import argparse
import copy
import json
import math
import re
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath

from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageChops, ImageStat


def number(value):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("数值必须有限")
    return f"{value:.4f}"


def flag(value):
    return "True" if value else "False"


def rgba(value, name):
    """[R,G,B] / [R,G,B,A] 或 "#rrggbb" / "#rrggbbaa"，返回 4 个 0–255 整数。"""
    if isinstance(value, str):
        text = value.lstrip("#")
        if not re.fullmatch(r"[0-9a-fA-F]{6}([0-9a-fA-F]{2})?", text):
            raise ValueError(f"无效颜色 {value!r}：{name}")
        value = [int(text[i:i + 2], 16) for i in range(0, len(text), 2)]
    value = list(value)
    if len(value) == 3:
        value.append(255)
    if len(value) != 4 or not all(isinstance(v, int) and 0 <= v <= 255 for v in value):
        raise ValueError(f"无效颜色 {value!r}：{name}")
    return value


ALIGNS = {"left": "HT_Left", "center": "HT_Center", "right": "HT_Right"}


def shear(image, degrees, ax, ay):
    """按 Cocos RotationSkewX（RotationSkewY=0）绕锚点斜切；正值顶部右倾。返回新图和左侧扩边像素。"""
    tan = math.tan(math.radians(degrees))
    cos = math.cos(math.radians(degrees))
    w, h = image.size
    pad = math.ceil(h * abs(tan)) + 1
    top = (1 - ay) * h
    data = (1, tan, -pad - top * tan, 0, 1 / cos, top - top / cos)
    return image.transform((w + pad * 2, h), Image.Transform.AFFINE, data,
                           Image.Resampling.BICUBIC), pad


def resolve(roots, name):
    path = PurePosixPath(name)
    if not name or path.is_absolute() or ".." in path.parts or "\\" in name:
        raise ValueError(f"需要资源根目录内的 POSIX 相对路径：{name!r}")
    for root in roots:
        candidate = Path(root).joinpath(*path.parts)
        if not candidate.is_file():
            continue
        parent = Path(root)
        for part in path.parts:
            if part not in {p.name for p in parent.iterdir()}:
                raise ValueError(f"资源路径大小写不一致：{name}")
            parent = parent / part
        return candidate
    raise FileNotFoundError(name)


def write_xml(root, output, force=False):
    output = Path(output)
    if output.exists() and not force:
        raise FileExistsError(f"拒绝覆盖已有文件：{output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(root, space="  ")
    output.write_bytes(ET.tostring(root, encoding="utf-8") + b"\n")


def fields(line):
    return {key: value.strip('"') for key, value in
            re.findall(r'(\w+)=("[^"\n]*"|[^\s]+)', line)}


def read_bmfont(path):
    pages, chars, kernings, height = {}, {}, {}, 0
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        data = fields(line)
        kind = line.split(" ", 1)[0]
        if kind == "common":
            height = int(data["lineHeight"])
        elif kind == "page":
            pages[int(data["id"])] = data["file"]
        elif kind == "char":
            chars[int(data["id"])] = {k: int(v) for k, v in data.items() if k != "letter"}
        elif kind == "kerning":
            kernings[int(data["first"]), int(data["second"])] = int(data["amount"])
    if height <= 0 or not pages:
        raise ValueError(f"不支持或无效的文本 BMFont：{path}")
    return pages, chars, kernings, height


def bmfont_image(path, text):
    pages, chars, kernings, height = read_bmfont(path)
    bitmaps = {key: Image.open(Path(path).parent / name).convert("RGBA")
               for key, name in pages.items()}
    cursor, previous, glyphs = 0, None, []
    for char in text:
        code = ord(char)
        if code not in chars:
            raise ValueError(f"BMFont 缺少字符 {char!r}：{path}")
        data = chars[code]
        cursor += kernings.get((previous, code), 0)
        glyphs.append((cursor, data))
        cursor += data["xadvance"]
        previous = code
    width = max([cursor, 1] + [x + d["xoffset"] + d["width"] for x, d in glyphs])
    image = Image.new("RGBA", (width, height))
    for x, data in glyphs:
        page = bitmaps[data.get("page", 0)]
        crop = page.crop((data["x"], data["y"], data["x"] + data["width"], data["y"] + data["height"]))
        image.alpha_composite(crop, (x + data["xoffset"], data["yoffset"]))
    return image


def inventory(directory, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    entries = []
    for path in sorted(Path(directory).rglob("*.png")):
        with Image.open(path) as source:
            image = source.convert("RGBA")
            entries.append({"path": path.relative_to(directory).as_posix(),
                            "size": list(image.size), "alpha_bbox": image.getchannel("A").getbbox()})
    (output / "inventory.json").write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n")
    for start in range(0, len(entries), 48):
        chunk = entries[start:start + 48]
        sheet = Image.new("RGB", (1000, math.ceil(len(chunk) / 4) * 220), (48, 58, 72))
        draw = ImageDraw.Draw(sheet)
        for index, entry in enumerate(chunk):
            x, y = index % 4 * 250, index // 4 * 220
            with Image.open(Path(directory) / entry["path"]) as source:
                image = source.convert("RGBA")
            image.thumbnail((238, 180))
            sheet.paste(image, (x + (250 - image.width) // 2, y + 10), image)
            label = f"{start + index + 1}: {entry['path']}"
            draw.text((x + 5, y + 194), label.encode("ascii", "replace").decode(), fill="white")
        sheet.save(output / f"contact-{start // 48 + 1:02d}.png")
    return entries


def make_csi(template, resource_root, directory, output, force=False):
    root = copy.deepcopy(ET.parse(template).getroot())
    prop = root.find("PropertyGroup")
    prop.set("Name", Path(output).stem)
    prop.set("ID", str(uuid.uuid4()))
    content = root.find("Content")
    images = content.find("ImageFiles")
    images.clear()
    folder = Path(resource_root) / directory
    font_pages = set()
    for fnt in folder.rglob("*.fnt"):
        pages, _, _, _ = read_bmfont(fnt)
        font_pages.update((fnt.parent / name).resolve() for name in pages.values())
    files = []
    for image in sorted(folder.rglob("*.png")):
        if image.resolve() in font_pages or image.name.startswith(("标注", "设计稿")):
            continue
        name = image.relative_to(resource_root).as_posix()
        resolve([resource_root], name)
        files.append(name)
    if not files:
        raise ValueError("没有可打包的 PNG")
    if len({p.casefold() for p in files}) != len(files):
        raise ValueError("素材路径存在大小写冲突")
    for name in files:
        ET.SubElement(images, "FilePathData", Path=name)
    write_xml(root, output, force)
    return files


TYPES = {"node": "SingleNodeObjectData", "panel": "PanelObjectData",
         "sprite": "SpriteObjectData", "image": "ImageViewObjectData",
         "button": "ButtonObjectData", "text": "TextObjectData",
         "bmfont": "TextBMFontObjectData", "loadingbar": "LoadingBarObjectData"}


def check_editor_attrs(attrs, version, name):
    if version == "3.10.0.0" and "BarEnabled" in attrs:
        raise ValueError(f"Cocos Studio 3.10.0.0 不支持 BarEnabled：{name}；"
                         "滚动条请在加载后用 setScrollBarEnabled(false) 关闭")


class Builder:
    """Rectangles use parent-local top-left coordinates. CSD positions use bottom-left."""
    def __init__(self, name, size, version, resource_roots, root_type="Scene"):
        self.roots = resource_roots
        self.version = version
        self.counter = 100
        self.root = ET.Element("GameFile")
        ET.SubElement(self.root, "PropertyGroup", Name=name, Type=root_type,
                      ID=str(uuid.uuid4()), Version=version)
        content = ET.SubElement(ET.SubElement(self.root, "Content", ctype="GameProjectContent"), "Content")
        ET.SubElement(content, "Animation", Duration="0", Speed="1.0000")
        self.scene = ET.SubElement(content, "ObjectData", Name=root_type, Tag="1",
                                   ctype="GameNodeObjectData")
        ET.SubElement(self.scene, "Size", X=number(size[0]), Y=number(size[1]))
        self.size = size

    def add(self, parent, name, kind, rect, resource=None, text="", font=None,
            font_size=30, color=(255, 255, 255, 255), anchor=(.5, .5),
            touch=False, visible=True, scale9=None, attrs=None, percent=100,
            italic=0, shadow=None, outline=None, align=None):
        if kind not in TYPES:
            raise ValueError(f"未知节点类型：{kind}")
        check_editor_attrs(attrs or {}, self.version, name)
        if kind != "text" and (italic or shadow or outline or align):
            raise ValueError(f"italic/shadow/outline/align 只用于 text：{name}")
        left, top, width, height = map(float, rect)
        pw, ph = pair(parent, "Size", "X", "Y")
        content_w, content_h = width, height
        sx = sy = 1
        if kind == "sprite":
            with Image.open(resolve(self.roots, resource["path"])) as image:
                content_w, content_h = image.size
            sx, sy = width / content_w, height / content_h
        elif kind == "bmfont":
            bitmap = bmfont_image(resolve(self.roots, font), text)
            content_w, content_h = bitmap.size
            sx, sy = width / content_w, height / content_h
        if min(width, height) < 0:
            raise ValueError("节点尺寸不能为负数")
        self.counter += 1
        data = dict(Name=name, ActionTag=str(self.counter), Tag=str(self.counter),
                    IconVisible=flag(kind == "node"), ctype=TYPES[kind],
                    LeftMargin=number(left), RightMargin=number(pw-left-width),
                    TopMargin=number(top), BottomMargin=number(ph-top-height))
        if touch or kind == "button":
            data["TouchEnable"] = "True"
        if not visible:
            data["Visible"] = "False"
        for key, value in (attrs or {}).items():
            if key in {"Name", "ActionTag", "Tag", "ctype"}:
                raise ValueError(f"attrs 不允许覆盖 {key}")
            data[key] = str(value)
        if kind in {"image", "button"}:
            data["Scale9Enable"] = flag(scale9 is not None)
        if kind == "panel":
            data.setdefault("ClipAble", "False")
            data.setdefault("BackColorAlpha", "0")
            data.setdefault("ComboBoxIndex", "0")
        if kind in {"text", "bmfont"}:
            if not font:
                raise ValueError("文字节点需要字体资源")
            data["LabelText"] = text
        if kind == "text":
            if align:
                if align not in ALIGNS:
                    raise ValueError(f"align 只能是 {'/'.join(ALIGNS)}：{name}")
                data["HorizontalAlignmentType"] = ALIGNS[align]
            if italic:
                if not math.isfinite(float(italic)) or abs(float(italic)) >= 45:
                    raise ValueError(f"italic 斜切角需在 ±45° 内：{name}")
                # sohoojs 美术与手调 CSD 的斜体都是单边 RotationSkewX，Studio/native/H5 均按斜切渲染
                data["RotationSkewX"] = number(italic)
            if outline:
                size = int(outline.get("size", 2))
                if size <= 0:
                    raise ValueError(f"描边宽度需为正整数：{name}")
                data.update(OutlineEnabled="True", OutlineSize=str(size))
            if shadow:
                ox, oy = shadow.get("offset", [2, -2])
                data.update(ShadowEnabled="True", ShadowOffsetX=number(ox), ShadowOffsetY=number(oy))
            data.update(FontSize=str(font_size), IsCustomSize="True",
                        HorizontalAlignmentType=data.get("HorizontalAlignmentType", "HT_Center"),
                        VerticalAlignmentType=data.get("VerticalAlignmentType", "VT_Center"))
        if kind == "loadingbar":
            if not 0 <= float(percent) <= 100:
                raise ValueError("进度必须为 0–100")
            data.setdefault("ProgressType","Left_To_Right")
            data["ProgressInfo"]=str(percent)
        if scale9 is not None:
            l, r, t, b = scale9
            with Image.open(resolve(self.roots, resource["path"])) as image:
                iw, ih = image.size
            if min(l,r,t,b) < 0 or l+r >= iw or t+b >= ih:
                raise ValueError(f"无效九宫格：{name}")
            data.update(LeftEage=str(l), RightEage=str(r), TopEage=str(t), BottomEage=str(b),
                        Scale9OriginX=str(l), Scale9OriginY=str(t),
                        Scale9Width=str(iw-l-r), Scale9Height=str(ih-t-b))
        children = parent.find("Children")
        if children is None:
            children = ET.SubElement(parent, "Children")
        node = ET.SubElement(children, "AbstractNodeData", data)
        ET.SubElement(node, "Size", X=number(content_w), Y=number(content_h))
        ET.SubElement(node, "AnchorPoint", ScaleX=number(anchor[0]), ScaleY=number(anchor[1]))
        px, py = left+anchor[0]*width, ph-top-(1-anchor[1])*height
        ET.SubElement(node, "Position", X=number(px), Y=number(py))
        ET.SubElement(node, "Scale", ScaleX=number(sx), ScaleY=number(sy))
        ET.SubElement(node, "CColor", R=str(color[0]), G=str(color[1]), B=str(color[2]), A=str(color[3]))
        ET.SubElement(node, "PrePosition", X=number(px/pw if pw else 0), Y=number(py/ph if ph else 0))
        ET.SubElement(node, "PreSize", X=number(content_w/pw if pw else 0), Y=number(content_h/ph if ph else 0))
        if resource:
            tags = ["NormalFileData", "PressedFileData", "DisabledFileData"] if kind == "button" else ["ImageFileData"] if kind == "loadingbar" else ["FileData"]
            for tag in tags:
                ET.SubElement(node, tag, Type="MarkedSubImage" if resource.get("plist") else "Normal",
                              Path=resource["path"], Plist=resource.get("plist", ""))
        if font:
            ET.SubElement(node, "LabelBMFontFile_CNB" if kind == "bmfont" else "FontResource",
                          Type="Normal", Path=font, Plist="")
        for tag, effect in (("OutlineColor", outline), ("ShadowColor", shadow)):
            if effect:
                r, g, b, a = rgba(effect.get("color", [0, 0, 0]), name)
                ET.SubElement(node, tag, A=str(a), R=str(r), G=str(g), B=str(b))
        if kind == "sprite":
            ET.SubElement(node, "BlendFunc", Src="1", Dst="771")
        return node


def pair(node, tag, x, y, default=(0, 0)):
    child = node.find(tag)
    if child is None:
        return default
    return float(child.get(x, default[0])), float(child.get(y, default[1]))


def check(csd, roots):
    root = csd if isinstance(csd,ET.Element) else ET.parse(csd).getroot()
    scene = root.find("./Content/Content/ObjectData")
    if root.tag != "GameFile" or scene is None or root.find("PropertyGroup") is None:
        raise ValueError("不是有效的 CSD GameFile 结构")
    ids, resources, atlases = set(), set(), set()
    skewed = []
    for node in [scene] + list(scene.iter("AbstractNodeData")):
        check_editor_attrs(node.attrib, root.find("PropertyGroup").get("Version"), node.get("Name"))
        inner = node.find("InnerNodeSize")
        if node.get("ctype") == "ScrollViewObjectData" and inner is not None:
            for key in ("Width", "Height"):
                value = inner.get(key, "")
                if re.fullmatch(r"[0-9]+", value) is None:
                    raise ValueError(f"InnerNodeSize.{key} 必须是非负整数字符串："
                                     f"{node.get('Name')}={value!r}；不能使用 436.0000 这样的浮点格式")
        ident = node.get("ActionTag")
        if ident is not None:
            if ident in ids:
                raise ValueError(f"重复 ActionTag：{ident}")
            ids.add(ident)
        names = [n.get("Name") for n in node.findall("./Children/AbstractNodeData")]
        if len(names) != len(set(names)):
            raise ValueError(f"兄弟节点重名：{node.get('Name')}")
        for tag, x, y, default in [("Size","X","Y",(0,0)), ("Position","X","Y",(0,0)),
                                    ("Scale","ScaleX","ScaleY",(1,1)), ("AnchorPoint","ScaleX","ScaleY",(0,0))]:
            values = pair(node, tag, x, y, default)
            if not all(math.isfinite(v) for v in values) or tag == "Size" and min(values) < 0:
                raise ValueError(f"无效 {tag}：{node.get('Name')}")
        rx, ry = float(node.get("RotationSkewX", 0)), float(node.get("RotationSkewY", 0))
        if not math.isfinite(rx + ry):
            raise ValueError(f"rotationSkew 无效：{node.get('Name')}")
        # 单边斜切是美术做斜体的常规用法，普通加载正常；只有 native 克隆该控件时会撞 CCNode 断言
        if abs(rx - ry) > .00001:
            skewed.append(node.get("Name"))
        for res in list(node):
            path = res.get("Path")
            if not path:
                continue
            actual = resolve(roots, path)
            resources.add(path)
            plist = res.get("Plist")
            if res.get("Type") == "MarkedSubImage":
                if not plist:
                    raise ValueError(f"图集资源没有 Plist：{path}")
                csi = resolve(roots, str(PurePosixPath(plist).with_suffix(".csi")))
                members = {f.get("Path") for f in ET.parse(csi).findall("./Content/ImageFiles/FilePathData")}
                if path not in members:
                    raise ValueError(f"图集描述中缺少帧：{path} -> {plist}")
                atlases.add(plist)
            if actual.suffix == ".fnt":
                pages, _, _, _ = read_bmfont(actual)
                for page in pages.values():
                    resolve(roots, str(PurePosixPath(path).parent / page))
        if node.get("Scale9Enable") == "True":
            resource = node.find("FileData")
            if resource is None:
                resource = node.find("NormalFileData")
            if resource is not None and resource.get("Path"):
                with Image.open(resolve(roots, resource.get("Path"))) as image:
                    iw, ih = image.size
                x,y,w,h = [float(node.get(k, 0)) for k in ("Scale9OriginX","Scale9OriginY","Scale9Width","Scale9Height")]
                if not all(math.isfinite(v) for v in (x,y,w,h)) or min(x,y) < 0 or min(w,h) <= 0 or x+w > iw or y+h > ih:
                    raise ValueError(f"九宫格超出原图：{node.get('Name')}")
    result = {"nodes": len(ids), "resources": len(resources), "source_atlases": sorted(atlases),
              "validation": "仅 CSD/CSI 源资源静态检查；未验证编辑器导出或运行时图集"}
    if skewed:
        result["warnings"] = [f"RotationSkewX/Y 不相等（单边斜切），native 克隆这些控件会触发断言，"
                              f"不要对它们或其祖先调用 clone：{', '.join(skewed)}"]
    return result


def build(layout, roots, output, force=False):
    spec = json.loads(Path(layout).read_text(encoding="utf-8"))
    builder = Builder(spec["name"], spec["canvas"], spec["version"], roots, spec.get("root_type","Scene"))

    def add(parent, item):
        if "clone" in item:
            source = ET.parse(resolve(roots,item["clone"]["csd"]))
            matches = source.findall(f".//AbstractNodeData[@Name='{item['clone']['node']}']")
            if len(matches) != 1:
                raise ValueError(f"复制节点不唯一或不存在：{item['clone']}")
            result = copy.deepcopy(matches[0])
            children = parent.find("Children")
            if children is None:
                children = ET.SubElement(parent,"Children")
            children.append(result)
            result.set("Name",item.get("name",result.get("Name")))
        else:
            keys = {key:value for key,value in item.items() if key != "children"}
            keys["kind"] = keys.pop("type")
            result = builder.add(parent,**keys)
        for child in item.get("children",[]):
            add(result,child)
    for item in spec["nodes"]:
        add(builder.scene,item)
    for index,node in enumerate(builder.scene.iter("AbstractNodeData"),100):
        node.set("Tag",str(index))
        node.set("ActionTag",str(index))
    result=check(builder.root,roots)
    write_xml(builder.root,output,force)
    return result


def nine_slice(image, size, node):
    w, h = size
    x, y, cw, ch = [int(float(node.get(k, 0))) for k in ("Scale9OriginX","Scale9OriginY","Scale9Width","Scale9Height")]
    right, bottom = image.width-x-cw, image.height-y-ch
    if w < x+right or h < y+bottom:
        raise ValueError(f"九宫格目标小于固定边：{node.get('Name')}")
    srcx, srcy = [0,x,x+cw,image.width], [0,y,y+ch,image.height]
    dstx, dsty = [0,x,w-right,w], [0,y,h-bottom,h]
    out = Image.new("RGBA", size)
    for row in range(3):
        for col in range(3):
            target = dstx[col+1]-dstx[col], dsty[row+1]-dsty[row]
            if min(target) <= 0:
                continue
            crop = image.crop((srcx[col],srcy[row],srcx[col+1],srcy[row+1]))
            if min(crop.size) <= 0:
                continue
            out.paste(crop.resize(target, Image.Resampling.LANCZOS), (dstx[col],dsty[row]))
    return out


def preview(csd, roots, output, width=None, force=False):
    check(csd, roots)
    scene = ET.parse(csd).getroot().find("./Content/Content/ObjectData")
    sw, sh = pair(scene,"Size","X","Y")
    canvas_w = int(width or sw)
    canvas_h = round(sh)
    offset_x = 0
    canvas = Image.new("RGBA", (canvas_w,canvas_h))

    def adapt(node, parent_size):
        old_w,old_h = pair(node,"Size","X","Y")
        w,h = old_w,old_h
        pre_w,pre_h = pair(node,"PreSize","X","Y")
        if node.get("PercentWidthEnable") == "True" or node.get("PercentWidthEnabled") == "True":
            w = parent_size[0]*pre_w
        if node.get("PercentHeightEnable") == "True" or node.get("PercentHeightEnabled") == "True":
            h = parent_size[1]*pre_h
        node.find("Size").set("X",number(w))
        node.find("Size").set("Y",number(h))
        px,py = pair(node,"Position","X","Y")
        ax,ay = pair(node,"AnchorPoint","ScaleX","ScaleY")
        pre_x,pre_y = pair(node,"PrePosition","X","Y")
        if node.get("PositionPercentXEnabled") == "True":
            px = parent_size[0]*pre_x
        if node.get("PositionPercentYEnabled") == "True":
            py = parent_size[1]*pre_y
        if node.get("HorizontalEdge") == "RightEdge":
            px = parent_size[0]-float(node.get("RightMargin",0))-(1-ax)*w
        elif node.get("HorizontalEdge") == "LeftEdge":
            px = float(node.get("LeftMargin",0))+ax*w
        if node.get("VerticalEdge") == "TopEdge":
            py = parent_size[1]-float(node.get("TopMargin",0))-(1-ay)*h
        elif node.get("VerticalEdge") == "BottomEdge":
            py = float(node.get("BottomMargin",0))+ay*h
        position = node.find("Position")
        if position is not None:
            position.set("X",number(px))
            position.set("Y",number(py))
        for child in node.findall("./Children/AbstractNodeData"):
            adapt(child,(w,h))

    scene.find("Size").set("X",number(canvas_w))
    for child in scene.findall("./Children/AbstractNodeData"):
        adapt(child,(canvas_w,sh))

    def visit(node, parent_origin, parent_scale, clip=None):
        if node.get("Visible", "True") == "False":
            return
        name = node.get("Name")
        italic = float(node.get("RotationSkewX",0))
        for key in ("RotationSkewY","SkewX","SkewY"):
            if float(node.get(key,0)):
                raise ValueError(f"离线预览不支持 {key}：{name}")
        if italic and node.find("./Children/AbstractNodeData") is not None:
            raise ValueError(f"离线预览只支持无子节点控件的单边 RotationSkewX：{name}")
        kind = node.get("ctype")
        if kind not in set(TYPES.values()) | {"GameNodeObjectData"}:
            raise ValueError(f"离线预览不支持 {kind}：{name}")
        w,h = pair(node,"Size","X","Y")
        px,py = pair(node,"Position","X","Y")
        ax,ay = pair(node,"AnchorPoint","ScaleX","ScaleY")
        sx,sy = pair(node,"Scale","ScaleX","ScaleY",(1,1))
        if min(sx,sy) <= 0:
            raise ValueError(f"离线预览不支持非正缩放：{name}")
        gx,gy = parent_scale[0]*sx, parent_scale[1]*sy
        origin = (parent_origin[0]+parent_scale[0]*(px-ax*w*sx),
                  parent_origin[1]+parent_scale[1]*(py-ay*h*sy))
        bounds = (round(origin[0]+offset_x), round(sh-origin[1]-h*gy),
                  round(origin[0]+w*gx+offset_x), round(sh-origin[1]))
        if node.get("ClipAble") == "True":
            clip = bounds if clip is None else (max(clip[0],bounds[0]),max(clip[1],bounds[1]),min(clip[2],bounds[2]),min(clip[3],bounds[3]))
        children = sorted(node.findall("./Children/AbstractNodeData"), key=lambda n:int(n.get("ZOrder",0)))
        for child in children:
            if int(child.get("ZOrder",0)) < 0:
                visit(child,origin,(gx,gy),clip)
        own = None
        tinted = False
        resource = node.find("FileData")
        if resource is None:
            resource = node.find("NormalFileData")
        if resource is None:
            resource = node.find("ImageFileData")
        size = max(1,round(w)), max(1,round(h))
        if resource is not None and resource.get("Path"):
            own = Image.open(resolve(roots,resource.get("Path"))).convert("RGBA")
            own = nine_slice(own,size,node) if node.get("Scale9Enable") == "True" else own.resize(size,Image.Resampling.LANCZOS)
            if node.get("FlipX") == "True":
                own = ImageOps.mirror(own)
            if node.get("FlipY") == "True":
                own = ImageOps.flip(own)
            if kind == "LoadingBarObjectData":
                progress=float(node.get("ProgressInfo",100))/100
                cutoff=round(own.width*progress)
                empty=Image.new("RGBA",own.size)
                start=0 if node.get("ProgressType","Left_To_Right") == "Left_To_Right" else own.width-cutoff
                empty.paste(own.crop((start,0,start+cutoff,own.height)),(start,0))
                own=empty
        if kind == "TextBMFontObjectData":
            font = node.find("LabelBMFontFile_CNB")
            own = bmfont_image(resolve(roots,font.get("Path")),node.get("LabelText", ""))
        elif kind == "TextObjectData":
            font = ImageFont.truetype(str(resolve(roots,node.find("FontResource").get("Path"))),int(node.get("FontSize",30)))
            own = Image.new("RGBA",size)
            draw = ImageDraw.Draw(own)
            text = node.get("LabelText", "")
            stroke = int(node.get("OutlineSize",0)) if node.get("OutlineEnabled") == "True" else 0
            left,top,right,bottom = draw.textbbox((0,0),text,font=font,stroke_width=stroke)
            align = node.get("HorizontalAlignmentType","HT_Left")
            x = (size[0]-(right-left))/2-left if align == "HT_Center" else size[0]-(right-left)-left if align == "HT_Right" else -left
            y = (size[1]-(bottom-top))/2-top
            def effect(tag):
                c = node.find(tag)
                return tuple(int(c.get(k,255)) for k in "RGBA") if c is not None else (0,0,0,255)
            if node.get("ShadowEnabled") == "True":
                ox,oy = float(node.get("ShadowOffsetX",2)),float(node.get("ShadowOffsetY",-2))
                draw.text((x+ox,y-oy),text,font=font,fill=effect("ShadowColor"),stroke_width=stroke,stroke_fill=effect("ShadowColor"))
            draw.text((x,y),text,font=font,fill=effect("CColor")[:3]+(255,),stroke_width=stroke,stroke_fill=effect("OutlineColor"))
            tinted = True
        if own is not None:
            color = node.find("CColor")
            if color is not None and tinted:
                alpha = int(color.get("A",255))
                own.putalpha(own.getchannel("A").point(lambda v:v*alpha//255))
            elif color is not None:
                channels = own.split()
                own = Image.merge("RGBA",tuple(channel.point(lambda v, c=int(color.get(k,255)):v*c//255)
                                                 for channel,k in zip(channels,"RGBA")))
            target = max(1,bounds[2]-bounds[0]),max(1,bounds[3]-bounds[1])
            own = own.resize(target,Image.Resampling.LANCZOS)
            pad = 0
            if italic:
                own,pad = shear(own,italic,ax,ay)
            layer = Image.new("RGBA",canvas.size)
            layer.paste(own,(bounds[0]-pad,bounds[1]))
            if clip is not None:
                clipped = Image.new("RGBA",canvas.size)
                if clip[2] > clip[0] and clip[3] > clip[1]:
                    clipped.paste(layer.crop(clip),clip[:2])
                layer = clipped
            canvas.alpha_composite(layer)
        for child in children:
            if int(child.get("ZOrder",0)) >= 0:
                visit(child,origin,(gx,gy),clip)

    visit(scene,(0,0),(1,1))
    output = Path(output)
    if output.exists() and not force:
        raise FileExistsError(output)
    output.parent.mkdir(parents=True,exist_ok=True)
    canvas.save(output)
    return {"output":str(output),"size":canvas.size,"renderer":"离线静态预览；字体基线/混合/适配以编辑器和引擎为准"}


def compare(design, crop, preview_path, output):
    output=Path(output)
    targets=[output/"design-crop.png",output/"overlay.png",output/"side-by-side.png"]
    if any(path.exists() for path in targets):
        raise FileExistsError("对照输出已存在，请使用新目录")
    x,y,w,h=crop
    with Image.open(design) as image:
        if min(x,y) < 0 or min(w,h) <= 0 or x+w > image.width or y+h > image.height:
            raise ValueError("设计稿裁剪区域无效")
        reference=image.convert("RGBA").crop((x,y,x+w,y+h))
    with Image.open(preview_path) as image:
        predicted=image.convert("RGBA")
    if predicted.size != reference.size:
        raise ValueError("预览与设计有效区域尺寸不一致；先核对逻辑画布，不自动拉伸")
    half=predicted.copy()
    half.putalpha(half.getchannel("A").point(lambda alpha:alpha//2))
    overlay=Image.alpha_composite(reference,half)
    plain=Image.new("RGBA",reference.size,(40,50,65,255))
    plain.alpha_composite(predicted)
    montage=Image.new("RGBA",(w*2,h))
    montage.paste(reference,(0,0))
    montage.paste(plain,(w,0))
    output.mkdir(parents=True,exist_ok=True)
    for path,image in zip(targets,[reference,overlay,montage]):
        image.save(path)
    return {"outputs":[str(p) for p in targets],"note":"overlay 为 UI 叠加定位对照，不代表编辑器实测；未生成误差评分"}


def match_image(design,slice_path,near,radius=24,scales=(1,)):
    """Locate an opaque asset core near a measured point; visual review remains necessary."""
    with Image.open(design) as image:
        reference=image.convert("RGB")
    with Image.open(slice_path) as image:
        source=image.convert("RGBA")
    candidates=[]
    for scale in scales:
        w,h=round(source.width*scale),round(source.height*scale)
        if min(w,h) <= 0:
            raise ValueError("匹配尺寸必须为正")
        sample=source.resize((w,h),Image.Resampling.LANCZOS)
        small=(max(1,w//4),max(1,h//4))
        alpha=sample.getchannel("A").resize(small,Image.Resampling.NEAREST).point(lambda a:255 if a >= 250 else 0)
        if not alpha.getbbox():
            raise ValueError("素材没有足够不透明的像素，无法做局部匹配")
        sample=sample.convert("RGB").resize(small,Image.Resampling.BILINEAR)

        def score(x,y):
            if x < 0 or y < 0 or x+w > reference.width or y+h > reference.height:
                return float("inf")
            crop=reference.crop((x,y,x+w,y+h)).resize(small,Image.Resampling.BILINEAR)
            return sum(ImageStat.Stat(ImageChops.difference(sample,crop),alpha).mean)/3

        coarse=min((score(x,y),x,y) for y in range(near[1]-radius,near[1]+radius+1,4)
                   for x in range(near[0]-radius,near[0]+radius+1,4))
        _,cx,cy=coarse
        best=min((score(x,y),x,y) for y in range(cy-3,cy+4) for x in range(cx-3,cx+4))
        candidates.append((*best,scale,w,h))
    error,x,y,scale,w,h=min(candidates)
    if not math.isfinite(error):
        raise ValueError("搜索范围没有可用位置")
    return dict(rect=[x,y,w,h],scale=scale,opaque_rgb_error=round(error,3),
                note="仅局部素材匹配候选；需看图确认遮挡、背景和适配关系")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command",required=True)
    inv = sub.add_parser("inventory")
    inv.add_argument("--input",required=True)
    inv.add_argument("--output",required=True)
    csi = sub.add_parser("csi")
    csi.add_argument("--template",required=True)
    csi.add_argument("--resource-root",required=True)
    csi.add_argument("--directory",required=True)
    csi.add_argument("--output",required=True)
    csi.add_argument("--force",action="store_true")
    builder = sub.add_parser("build")
    builder.add_argument("--layout",required=True)
    builder.add_argument("--resource-root",action="append",required=True)
    builder.add_argument("--output",required=True)
    builder.add_argument("--force",action="store_true")
    comparison=sub.add_parser("compare")
    comparison.add_argument("--design",required=True)
    comparison.add_argument("--crop",required=True,type=int,nargs=4)
    comparison.add_argument("--preview",required=True)
    comparison.add_argument("--output",required=True)
    matcher=sub.add_parser("match")
    matcher.add_argument("--design",required=True)
    matcher.add_argument("--slice",required=True)
    matcher.add_argument("--near",nargs=2,type=int,required=True)
    matcher.add_argument("--radius",type=int,default=24)
    matcher.add_argument("--scales",type=float,nargs="+",default=[1])
    for name in ("check","preview"):
        command = sub.add_parser(name)
        command.add_argument("--csd",required=True)
        command.add_argument("--resource-root",action="append",required=True)
        if name == "preview":
            command.add_argument("--output",required=True)
            command.add_argument("--width",type=int)
            command.add_argument("--force",action="store_true")
    args = parser.parse_args()
    if args.command == "inventory":
        entries = inventory(args.input,args.output)
        result = {"images":len(entries),"inventory":str(Path(args.output)/"inventory.json"),"contacts":math.ceil(len(entries)/48)}
    elif args.command == "csi":
        files = make_csi(args.template,args.resource_root,args.directory,args.output,args.force)
        result = {"images":len(files),"output":args.output}
    elif args.command == "check":
        result = check(args.csd,args.resource_root)
    elif args.command == "build":
        result = build(args.layout,args.resource_root,args.output,args.force)
    elif args.command == "compare":
        result = compare(args.design,args.crop,args.preview,args.output)
    elif args.command == "match":
        result = match_image(args.design,args.slice,args.near,args.radius,args.scales)
    else:
        result = preview(args.csd,args.resource_root,args.output,args.width,args.force)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__ == "__main__":
    main()
