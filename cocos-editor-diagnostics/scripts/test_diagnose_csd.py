import base64
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

from diagnose_csd import MARKER, decode_remote, local_report, relative_name, ssh_command


class DiagnosticsTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def csd(self,name='Page.csd',width='436',height='225',reference=None):
        root=ET.Element('GameFile')
        ET.SubElement(root,'PropertyGroup',Name='Page',Version='3.10.0.0')
        scene=ET.SubElement(ET.SubElement(ET.SubElement(root,'Content'),'Content'),'ObjectData',Name='Scene')
        node=ET.SubElement(ET.SubElement(scene,'Children'),'AbstractNodeData',Name='m_attrs',ctype='ScrollViewObjectData',ActionTag='1')
        ET.SubElement(node,'Size',X='436.0000',Y='225.0000')
        ET.SubElement(node,'InnerNodeSize',Width=width,Height=height)
        if reference:
            ref=ET.SubElement(ET.SubElement(node,'Children'),'AbstractNodeData',Name='row',ctype='ProjectNodeObjectData',ActionTag='2')
            ET.SubElement(ref,'FileData',Path=reference)
        path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True)
        ET.ElementTree(root).write(path,encoding='utf-8')
        return root,node,path

    def test_integer_inner_and_floating_regular_size(self):
        self.csd()
        result=local_report(self.root,['Page.csd'])
        self.assertEqual(result['files'][0]['issues'],[])

    def test_locates_both_bad_fields(self):
        self.csd(width='436.0000',height='225.0000')
        issues=local_report(self.root,['Page.csd'])['files'][0]['issues']
        self.assertEqual({x['field'] for x in issues},{'InnerNodeSize.Width','InnerNodeSize.Height'})
        self.assertEqual(issues[0]['node'],'m_attrs')

    def test_unsupported_attribute_is_not_assumed_root_cause(self):
        root,node,path=self.csd();node.set('BarEnabled','False');ET.ElementTree(root).write(path)
        issue=local_report(self.root,['Page.csd'])['files'][0]['issues'][0]
        self.assertEqual(issue['severity'],'warning')

    def test_dependency_cycle_terminates(self):
        self.csd(reference='Row.csd');self.csd('Row.csd',reference='Page.csd')
        result=local_report(self.root,['Page.csd'])
        self.assertEqual(len(result['files']),2)
        self.assertFalse(result['truncated'])

    def test_missing_dependency_and_project_registration_are_different(self):
        self.csd(reference='Row.csd')
        issues=local_report(self.root,['Page.csd'])['files'][0]['issues']
        self.assertEqual(issues[0]['code'],'missing_reference')
        self.csd('Row.csd')
        project=self.root/'Project.ccs';project.write_text('<Solution><SolutionFolder /></Solution>')
        issue=local_report(self.root,['Page.csd'],project)['files'][0]['issues'][0]
        self.assertEqual(issue['code'],'project_registration')
        self.assertEqual(issue['severity'],'warning')

    def test_invalid_reference_and_xml_line_number(self):
        self.csd(reference='../outside.csd')
        issue=local_report(self.root,['Page.csd'])['files'][0]['issues'][0]
        self.assertEqual(issue['code'],'invalid_reference')
        (self.root/'Bad.csd').write_text('<GameFile>\n<broken>\n</GameFile>')
        issue=local_report(self.root,['Bad.csd'])['files'][0]['issues'][0]
        self.assertEqual(issue['code'],'xml_syntax');self.assertEqual(issue['line'],3)

    def test_remote_utf8_report_and_transport_failure(self):
        report={'files':[{'file':'中文.csd','exception_chain':['输入字符串格式不正确']}], 'mode':'windows'}
        payload=base64.b64encode(json.dumps(report,ensure_ascii=False).encode()).decode()
        self.assertEqual(decode_remote(('banner\n'+MARKER+payload+'\r\n').encode()),report)
        with self.assertRaisesRegex(RuntimeError,'不能归因于 CSD'):
            decode_remote(b'', '连接失败'.encode('gb18030'))

    def test_ssh_target_and_resource_paths_are_not_shell_code(self):
        for name in ('../a.csd','E:/a.csd','/etc/file',''):
            with self.assertRaises(ValueError):relative_name(name)
        with self.assertRaises(ValueError):ssh_command('host -oProxyCommand=evil',22,'powershell.exe')
        command=ssh_command('peter.dai@192.168.101.17',22,r'C:\Windows\SysWOW64\WindowsPowerShell\v1.0\powershell.exe')
        self.assertEqual(command[-2],'peter.dai@192.168.101.17')
        self.assertIn('SysWOW64',command[-1]);self.assertLess(len(command[-1]),2000)

    def test_cli_exit_status_and_no_input_changes(self):
        self.csd(width='436.0000')
        path=self.root/'Page.csd';before=path.read_bytes()
        output=self.root/'report.json'
        result=subprocess.run([sys.executable,str(Path(__file__).with_name('diagnose_csd.py')),'--output',str(output),
            'local','--root',str(self.root),'--file','Page.csd'],capture_output=True)
        self.assertEqual(result.returncode,1)
        self.assertEqual(json.loads(output.read_text())['files'][0]['issues'][0]['code'],'inner_size_integer')
        self.assertEqual(path.read_bytes(),before)


if __name__=='__main__':unittest.main()
