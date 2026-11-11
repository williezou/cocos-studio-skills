"""Observable image, layout and source-reference checks; no project mutations."""
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image
from cocos_ui import Builder, build, check, make_csi, pair, preview, resolve, write_xml, match_image, shear
from pack_atlas import pack, visible_equal


class ToolsTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        (self.root/"ui/images").mkdir(parents=True)
        self.csi=self.root/"ui/images.csi"

    def tearDown(self):
        self.tmp.cleanup()

    def image(self,name="a.png",size=(20,10),color=(10,40,90,255)):
        path=self.root/"ui/images"/name
        Image.new("RGBA",size,color).save(path)
        return "ui/images/"+name

    def descriptor(self,names,size=128,trim=False):
        root=ET.Element("PlistInfoProjectFile")
        ET.SubElement(root,"PropertyGroup",Name="images",Version="3.10.0.0",ID="sample",Type="Plist")
        content=ET.SubElement(root,"Content",PicturePadding="2",AllowTrim=str(trim),AllowRotation="False",SortAlgorithm="MaxRects")
        files=ET.SubElement(content,"ImageFiles")
        for name in names:
            ET.SubElement(files,"FilePathData",Path=name)
        ET.SubElement(content,"MaxSize",Width=str(size),Height=str(size))
        write_xml(root,self.csi)

    def test_coordinates_scaling_and_actual_csd_preview(self):
        name=self.image()
        self.descriptor([name])
        layout={"name":"Page","version":"3.10.0.0","canvas":[100,80],"nodes":[{
            "name":"m_icon","type":"sprite","rect":[10,20,40,20],"anchor":[.25,.75],
            "resource":{"path":name,"plist":"ui/images.plist"}}]}
        spec=self.root/"layout.json"
        spec.write_text(json.dumps(layout))
        csd=self.root/"Page.csd"
        build(spec,[self.root],csd)
        node=ET.parse(csd).find(".//AbstractNodeData")
        self.assertEqual(pair(node,"Position","X","Y"),(20,55))
        self.assertEqual(pair(node,"Scale","ScaleX","ScaleY"),(2,2))
        preview(csd,[self.root],self.root/"preview.png")
        with Image.open(self.root/"preview.png") as image:
            self.assertEqual(image.getchannel("A").getbbox(),(10,20,50,40))

    def test_nested_member_names_survive_build(self):
        layout = {"name": "Rows", "version": "3.10.0.0", "canvas": [100, 80], "nodes": [{
            "name": "m_singleAttrs", "type": "node", "rect": [0, 0, 100, 80],
            "children": [{"name": "m_row" + str(i), "type": "node", "rect": [0, i * 20, 100, 20],
                          "children": [{"name": "m_txtName", "type": "node", "rect": [0, 0, 10, 10]},
                                       {"name": "decoration", "type": "node", "rect": [10, 0, 10, 10]}]}
                         for i in (1, 2)]}]}
        spec = self.root / "rows.json"
        spec.write_text(json.dumps(layout))
        csd = self.root / "Rows.csd"
        build(spec, [self.root], csd)
        group = ET.parse(csd).find(".//AbstractNodeData[@Name='m_singleAttrs']")
        for i in (1, 2):
            row = group.find("./Children/AbstractNodeData[@Name='m_row" + str(i) + "']")
            self.assertIsNotNone(row)
            self.assertEqual([n.get("Name") for n in row.findall("./Children/AbstractNodeData")],
                             ["m_txtName", "decoration"])

    def test_bad_source_does_not_write_csd(self):
        layout={"name":"Bad","version":"3.10.0.0","canvas":[100,80],"nodes":[{
            "name":"m_icon","type":"sprite","rect":[0,0,20,10],"resource":{"path":"missing.png"}}]}
        spec=self.root/"bad.json"
        spec.write_text(json.dumps(layout))
        with self.assertRaises(FileNotFoundError):
            build(spec,[self.root],self.root/"Bad.csd")
        self.assertFalse((self.root/"Bad.csd").exists())

    def test_bar_enabled_rejected_before_build_and_in_existing_csd(self):
        layout={"name":"BadScroll","version":"3.10.0.0","canvas":[100,80],"nodes":[{
            "name":"m_scroll","type":"panel","rect":[0,0,100,80],"attrs":{"BarEnabled":"False"}}]}
        source=self.root/"layout.json"
        source.write_text(json.dumps(layout))
        output=self.root/"BadScroll.csd"
        with self.assertRaisesRegex(ValueError,"setScrollBarEnabled"):
            build(source,[self.root],output)
        self.assertFalse(output.exists())
        builder=Builder("Page",[100,80],"3.10.0.0",[self.root])
        node=builder.add(builder.scene,"m_scroll","panel",[0,0,100,80])
        node.set("ctype","ScrollViewObjectData")
        node.set("BarEnabled","False")
        write_xml(builder.root,output)
        with self.assertRaisesRegex(ValueError,"BarEnabled"):
            check(output,[self.root])
        node.attrib.pop("BarEnabled")
        self.assertEqual(check(builder.root,[self.root])["nodes"],1)

    def test_scroll_inner_size_uses_integer_strings(self):
        builder=Builder("Page",[436,225],"3.10.0.0",[self.root])
        node=builder.add(builder.scene,"m_scroll","panel",[0,0,436,225])
        node.set("ctype","ScrollViewObjectData")
        inner=ET.SubElement(node,"InnerNodeSize",Width="436",Height="225")
        self.assertEqual(check(builder.root,[self.root])["nodes"],1)
        for key in ("Width","Height"):
            original=inner.get(key)
            for invalid in (original+".0000","-1","nan"):
                inner.set(key,invalid)
                with self.assertRaisesRegex(ValueError,"InnerNodeSize."+key):
                    check(builder.root,[self.root])
            inner.set(key,original)
        self.assertEqual(check(builder.root,[self.root])["nodes"],1)

    def test_roundtrip_trim_offset_and_extrusion(self):
        name=self.image(size=(40,30),color=(155,44,77,0))
        image=Image.new("RGBA",(40,30),(155,44,77,0))
        image.paste((20,40,80,180),(19,3,27,12))
        image.save(self.root/name)
        self.descriptor([name],trim=True)
        result=pack(self.csi,[self.root],self.root/"packed")
        self.assertEqual(result["pixel_roundtrip"],"passed")
        manifest=json.loads((self.root/"packed/images.atlas.json").read_text())
        x,y,w,h=manifest["frames"][name]["rect"]
        self.assertEqual((w,h),(8,9))
        with Image.open(self.root/"packed/images.png") as page:
            self.assertEqual(page.getpixel((x-1,y)),page.getpixel((x,y)))
            self.assertEqual(page.getpixel((x+w,y+h)),page.getpixel((x+w-1,y+h-1)))

    def test_multi_page_and_oversized_input(self):
        names=[self.image("a.png",(40,40)),self.image("b.png",(40,40))]
        self.descriptor(names,size=64)
        result=pack(self.csi,[self.root],self.root/"packed")
        self.assertEqual(len(result["pages"]),2)
        self.image("a.png",(70,40))
        with self.assertRaises(ValueError):
            pack(self.csi,[self.root],self.root/"bad-pack")
        self.assertFalse((self.root/"bad-pack").exists())

    def test_missing_membership_and_duplicate_action_tag(self):
        first=self.image()
        other=self.image("b.png")
        self.descriptor([first])
        builder=Builder("Page",[100,80],"3.10.0.0",[self.root])
        builder.add(builder.scene,"m_a","image",[0,0,20,10],resource={"path":other,"plist":"ui/images.plist"})
        with self.assertRaises(ValueError):
            check(builder.root,[self.root])
        builder=Builder("Page",[100,80],"3.10.0.0",[self.root])
        a=builder.add(builder.scene,"m_a","node",[0,0,0,0])
        b=builder.add(builder.scene,"m_b","node",[0,0,0,0])
        b.set("ActionTag",a.get("ActionTag"))
        with self.assertRaises(ValueError):
            check(builder.root,[self.root])

    def test_one_sided_rotation_skew_warns(self):
        builder=Builder("Page",[100,80],"3.10.0.0",[self.root])
        node=builder.add(builder.scene,"m_txtSkew","node",[0,0,0,0])
        node.set("RotationSkewX","16.0000")
        result=check(builder.root,[self.root])
        self.assertIn("m_txtSkew",result["warnings"][0])
        node.set("RotationSkewY","16.0000")
        self.assertNotIn("warnings",check(builder.root,[self.root]))
        node.set("RotationSkewX","nan")
        with self.assertRaises(ValueError):
            check(builder.root,[self.root])

    def test_no_overwrite_and_safe_relative_paths(self):
        name=self.image()
        self.descriptor([name])
        pack(self.csi,[self.root],self.root/"packed")
        before=(self.root/"packed/images.plist").read_bytes()
        with self.assertRaises(FileExistsError):
            pack(self.csi,[self.root],self.root/"packed")
        self.assertEqual(before,(self.root/"packed/images.plist").read_bytes())
        with self.assertRaises(ValueError):
            resolve([self.root],"../a.png")

    def test_csi_excludes_font_page_and_design(self):
        image=self.image()
        self.image("font.png")
        self.image("标注_test.png")
        (self.root/"ui/images/font.fnt").write_text('common lineHeight=10\npage id=0 file="font.png"\n')
        self.descriptor([image])
        output=self.root/"output.csi"
        files=make_csi(self.csi,self.root,"ui/images",output)
        self.assertEqual(files,[image])
        self.assertEqual(ET.parse(output).find("Content").get("PicturePadding"),"2")

    def test_loadingbar_uses_reader_field_and_crops(self):
        name=self.image()
        self.descriptor([name])
        builder=Builder("Page",[100,80],"3.10.0.0",[self.root])
        bar=builder.add(builder.scene,"m_bar","loadingbar",[10,20,20,10],resource={"path":name,"plist":"ui/images.plist"},percent=25)
        self.assertIsNotNone(bar.find("ImageFileData"))
        csd=self.root/"Page.csd"
        write_xml(builder.root,csd)
        preview(csd,[self.root],self.root/"bar.png")
        with Image.open(self.root/"bar.png") as image:
            self.assertEqual(image.getchannel("A").getbbox(),(10,20,15,30))

    def test_text_style_fields_write_studio_attributes(self):
        (self.root/"fonts").mkdir()
        (self.root/"fonts/a.ttf").write_bytes(b"")
        builder=Builder("Page",[100,80],"3.10.0.0",[self.root])
        text=builder.add(builder.scene,"m_txtName","text",[0,0,60,20],text="苍穹竿",font="fonts/a.ttf",
                         italic=9,align="left",shadow={"color":"#012e81","offset":[2,-2]},outline={"color":[0,0,0],"size":3})
        self.assertEqual(text.get("RotationSkewX"),"9.0000")
        self.assertIsNone(text.get("RotationSkewY"))
        self.assertEqual(text.get("HorizontalAlignmentType"),"HT_Left")
        self.assertEqual((text.get("ShadowEnabled"),text.get("ShadowOffsetY")),("True","-2.0000"))
        self.assertEqual(text.find("ShadowColor").attrib,{"A":"255","R":"1","G":"46","B":"129"})
        self.assertEqual((text.get("OutlineEnabled"),text.get("OutlineSize")),("True","3"))
        self.assertEqual(text.find("OutlineColor").get("A"),"255")
        self.assertIn("m_txtName",check(builder.root,[self.root])["warnings"][0])
        plain=builder.add(builder.scene,"m_txtPlain","text",[0,0,60,20],text="x",font="fonts/a.ttf")
        self.assertIsNone(plain.get("RotationSkewX"))
        self.assertIsNone(plain.find("ShadowColor"))
        for bad in ({"italic":50},{"align":"middle"},{"shadow":{"color":"#12"}}):
            with self.assertRaises(ValueError):
                builder.add(builder.scene,"m_bad","text",[0,0,1,1],text="x",font="fonts/a.ttf",**bad)
        with self.assertRaises(ValueError):
            builder.add(builder.scene,"m_badSprite","node",[0,0,1,1],italic=9)

    def test_preview_shears_leaf_by_rotation_skew_x(self):
        name=self.image(size=(10,40),color=(255,0,0,255))
        self.descriptor([name])
        builder=Builder("Page",[100,80],"3.10.0.0",[self.root])
        sprite=builder.add(builder.scene,"m_bar","sprite",[45,20,10,40],resource={"path":name,"plist":"ui/images.plist"})
        sprite.set("RotationSkewX","20.0000")
        csd=self.root/"Page.csd"
        write_xml(builder.root,csd)
        preview(csd,[self.root],self.root/"skew.png")
        with Image.open(self.root/"skew.png") as image:
            alpha=image.getchannel("A")
            top=alpha.crop((0,21,100,22)).getbbox()
            bottom=alpha.crop((0,58,100,59)).getbbox()
        self.assertGreater(top[0],50)
        self.assertLess(bottom[0],45)
        image,pad=shear(Image.new("RGBA",(10,40),(255,0,0,255)),20,.5,.5)
        self.assertEqual(image.size,(10+pad*2,40))
        child=builder.add(sprite,"m_child","node",[0,0,1,1])
        write_xml(builder.root,csd,force=True)
        with self.assertRaises(ValueError):
            preview(csd,[self.root],self.root/"nested.png")
        sprite.remove(sprite.find("Children"))
        sprite.set("RotationSkewY","20.0000")
        write_xml(builder.root,csd,force=True)
        with self.assertRaises(ValueError):
            preview(csd,[self.root],self.root/"rotated.png")

    def test_matching_finds_actual_slice_in_design(self):
        source=Image.new("RGBA",(20,12),(50,150,20,255))
        source.paste((200,10,30,255),(0,0,7,12))
        slice_path=self.root/"slice.png"
        source.save(slice_path)
        design=Image.new("RGBA",(100,80),(40,40,40,255))
        design.paste(source,(31,21))
        design_path=self.root/"design.png"
        design.save(design_path)
        result=match_image(design_path,slice_path,[30,20],8,[1])
        self.assertEqual(result["rect"],[31,21,20,12])


if __name__ == "__main__":
    unittest.main()
