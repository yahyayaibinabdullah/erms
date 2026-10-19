"""Validate/fill real OOXML and render that exact revision with LibreOffice.

No HTML reconstruction of a Word layout and no font substitution. Conversion
uses the existing API executable/timeout/size settings and a private profile.
"""
from copy import deepcopy
from hashlib import sha256
from html import escape
from io import BytesIO
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from zipfile import BadZipFile, ZipFile, ZipInfo, ZIP_DEFLATED

from docx import Document
from docx.text.paragraph import Paragraph
from lxml import etree
from fastapi import HTTPException

from ..document_conversion import _libreoffice_binary, ConversionUnavailable
from .template_contract import CONTRACTS, row_fields

MIME = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
FONT_DIRECTORY=Path(__file__).resolve().parents[1]/'messaging/pdf_assets/disposition'
NS = {'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
W = '{'+NS['w']+'}'
TOKEN = re.compile(r'\{\{\s*([#/]?[a-z][a-z0-9_.]*)\s*\}\}')
ARABIC = re.compile(r'[\u0621-\u064a]')
LATIN = re.compile(r'[A-Za-z]')


def invalid(code='disposition_template_invalid', status=422):
    raise HTTPException(status, detail={'code':code})


def parts(content, maximum):
    if not content or len(content)>maximum:invalid('disposition_template_size',413)
    try:
        archive=ZipFile(BytesIO(content))
        entries=archive.infolist()
        names=[p.filename for p in entries]
        if len(names)!=len(set(names)) or len(names)>2048 or sum(p.file_size for p in entries)>maximum:
            invalid('disposition_template_size',413)
        if any(p.flag_bits & 1 or p.filename.startswith('/') or '..' in Path(p.filename).parts for p in entries):invalid()
        values={p.filename:archive.read(p) for p in entries}
        archive.close()
        if not {'word/document.xml','[Content_Types].xml'}<=values.keys():invalid()
        for name,value in values.items():
            if any(s in name.lower() for s in ('vbaproject','embeddings/','activex/','_xmlsignatures/')):invalid()
            if name.endswith(('.xml','.rels')):
                if b'<!DOCTYPE' in value or b'<!ENTITY' in value:invalid()
                tree=etree.fromstring(value,etree.XMLParser(resolve_entities=False,no_network=True))
                if name.endswith('.rels') and any(r.get('TargetMode')=='External' for r in tree):invalid()
                if tree.xpath('//w:altChunk|//w:object|//w:del|//w:ins',namespaces=NS):invalid()
                instructions=tree.xpath('//w:instrText/text()|//w:fldSimple/@w:instr',namespaces=NS)
                if any(i.strip().split()[0].upper() not in ('PAGE','NUMPAGES') for i in instructions if i.strip()):invalid()
        return values
    except (BadZipFile,KeyError,ValueError,etree.XMLSyntaxError,RuntimeError):invalid()


def paragraphs(tree):
    return tree.findall('.//w:p',NS)


def paragraph_text(p):
    return ''.join(p.itertext()) if p.tag==W+'t' else ''.join(p.xpath('.//w:t/text()',namespaces=NS))


def inherited_property(node,styles,property_path,style_path,default=None):
    value=node.find(property_path,NS)
    if value is not None:return value.get(W+'val','1') not in ('0','false','off')
    style=node.find(style_path,NS);style_id=style.get(W+'val') if style is not None else 'Normal';seen=set()
    while style_id and style_id not in seen:
        seen.add(style_id);style=next((s for s in styles.findall('w:style',NS) if s.get(W+'styleId')==style_id),None)
        if style is None:break
        value=style.find(property_path,NS)
        if value is not None:return value.get(W+'val','1') not in ('0','false','off')
        based=style.find('w:basedOn',NS);style_id=based.get(W+'val') if based is not None else None
    return default


def validate(content, kind, maximum):
    if kind not in CONTRACTS:invalid('disposition_document_type_invalid')
    contract=CONTRACTS[kind];values=parts(content,maximum)
    trees={name:etree.fromstring(value) for name,value in values.items()
           if name=='word/document.xml' or re.fullmatch(r'word/(header|footer)\d+\.xml',name)}
    texts=[paragraph_text(p) for tree in trees.values() for p in paragraphs(tree)]
    combined='\n'.join(texts)
    if not ARABIC.search(combined) or not LATIN.search(combined):invalid('disposition_template_bilingual_required')
    first=next((p for p in paragraphs(trees['word/document.xml']) if paragraph_text(p).strip()),None)
    if first is None or not ARABIC.match(paragraph_text(first).lstrip()):invalid('disposition_template_bilingual_required')
    allowed=set(contract.fields)|set(row_fields(contract))
    markers={'#'+contract.group,'/'+contract.group} if contract.group else set()
    tokens=TOKEN.findall(combined)
    if set(tokens)-allowed-markers or '{{' in TOKEN.sub('',combined) or '}}' in TOKEN.sub('',combined):invalid()
    if not set(contract.fields)<=set(tokens):invalid('disposition_template_fields_missing')
    if contract.group:
        rows=[r for tree in trees.values() for r in tree.findall('.//w:tr',NS)
              if '#'+contract.group in TOKEN.findall(paragraph_text(r)) or '/'+contract.group in TOKEN.findall(paragraph_text(r))]
        if len(rows)!=1 or tokens.count('#'+contract.group)!=1 or tokens.count('/'+contract.group)!=1:invalid('disposition_template_repeat_invalid')
        rt=TOKEN.findall(paragraph_text(rows[0]))
        if not set(row_fields(contract))<=set(rt) or rt.index('#'+contract.group)>rt.index('/'+contract.group):invalid('disposition_template_repeat_invalid')
        if any(t in contract.fields for t in rt):invalid('disposition_template_repeat_invalid')
        outside=[t for tree in trees.values() for p in paragraphs(tree)
                 if rows[0] not in p.iterancestors() for t in TOKEN.findall(paragraph_text(p))]
        if set(row_fields(contract)) & set(outside):invalid('disposition_template_repeat_invalid')
    try:
        doc=Document(BytesIO(content))
        default=doc.styles['Normal'].font.name
        containers=[doc._element]+[part._element for part in doc.part.related_parts.values() if part.partname.endswith('.xml') and hasattr(part,'_element') and part._element.tag in (W+'hdr',W+'ftr')]
        for p in [Paragraph(p,doc) for container in containers for p in container.xpath('.//w:p')]:
            for run in p.runs:
                if not run.text.strip():continue
                style=run.style if run.style and run.style.font.name else p.style
                font=run.font.name
                seen=set()
                while not font and style is not None and style.style_id not in seen:
                    seen.add(style.style_id);font=style.font.name;style=style.base_style
                if (font or default or '').casefold()!='changa':invalid('disposition_template_changa_required')
                fonts=run._r.rPr.rFonts if run._r.rPr is not None else None
                if fonts is not None and any(fonts.get(W+k) not in (None,'Changa') for k in ('ascii','hAnsi','cs','eastAsia')):invalid('disposition_template_changa_required')
    except (ValueError,KeyError):invalid()
    # Resolve standard style inheritance as well as direct Word formatting.
    styles=etree.fromstring(values.get('word/styles.xml',('<w:styles xmlns:w="'+NS['w']+'"/>').encode()))
    default_bidi=styles.find('w:docDefaults/w:pPrDefault/w:pPr/w:bidi',NS)
    default_rtl=default_bidi is not None and default_bidi.get(W+'val','1') not in ('0','false','off')
    for tree in trees.values():
        for table in tree.findall('.//w:tbl',NS):
            if ARABIC.search(paragraph_text(table)) and not inherited_property(table,styles,'w:tblPr/w:bidiVisual','w:tblPr/w:tblStyle',False):invalid('disposition_template_direction_invalid')
        for p in paragraphs(tree):
            value=paragraph_text(p)
            if not value.strip():continue
            is_rtl=inherited_property(p,styles,'w:pPr/w:bidi','w:pPr/w:pStyle',default_rtl)
            if ARABIC.match(value.lstrip()) and not is_rtl:invalid('disposition_template_direction_invalid')
            if TOKEN.search(value) and is_rtl:invalid('disposition_template_direction_invalid')
    return values


def _replace(p, values):
    """Replace split Word runs without flattening surrounding run formatting."""
    nodes=p.findall('.//w:t',NS);original=''.join(n.text or '' for n in nodes)
    for match in reversed(list(TOKEN.finditer(original))):
        key=match.group(1)
        if key not in values:invalid('disposition_template_fields_missing')
        start,end=match.span();offset=0
        for node in nodes:
            text=node.text or '';a,b=offset,offset+len(text);offset=b
            if a<end and b>start:
                left=text[:max(0,start-a)];right=text[max(0,end-a):]
                node.text=left+(values[key] if a<=start<b else '')+right
                node.set('{http://www.w3.org/XML/1998/namespace}space','preserve')


def snapshot_values(kind,snapshot):
    contract=CONTRACTS[kind]
    expected={'fields',contract.group} if contract.group else {'fields'}
    if set(snapshot)-{'source'}!=expected or 'source' in snapshot and not isinstance(snapshot['source'],dict):invalid('disposition_document_snapshot_invalid')
    def clean(row,keys):
        if not isinstance(row,dict) or set(row)!=set(keys):invalid('disposition_document_snapshot_invalid')
        result={}
        for key,value in row.items():
            if isinstance(value,bool) or not isinstance(value,(str,int)) or not str(value).strip() or '{{' in str(value) or '}}' in str(value):invalid('disposition_document_snapshot_invalid')
            if (key.startswith(('counts.','totals.')) or key.split('.')[-1] in ('roots','descendant_aggregations','records','physical','digital','mixed','current_years','intermediate_years','physical_aggregations','mixed_aggregations','physical_records','mixed_records')) and (not isinstance(value,int) or value<0):invalid('disposition_document_snapshot_invalid')
            result[key]=str(value)
        return result
    scalar=clean(snapshot.get('fields'),contract.fields)
    rows=snapshot.get(contract.group,[]) if contract.group else []
    if not isinstance(rows,list):invalid('disposition_document_snapshot_invalid')
    return scalar,[clean(row,row_fields(contract)) for row in rows]


def fill(content,kind,snapshot,maximum):
    values=validate(content,kind,maximum);contract=CONTRACTS[kind]
    scalar,rows=snapshot_values(kind,snapshot)
    for name in list(values):
        if name!='word/document.xml' and not re.fullmatch(r'word/(header|footer)\d+\.xml',name):continue
        tree=etree.fromstring(values[name])
        if contract.group:
            for row in tree.findall('.//w:tr',NS):
                if '#'+contract.group not in TOKEN.findall(paragraph_text(row)):continue
                for data in rows:
                    clone=deepcopy(row)
                    for p in paragraphs(clone):_replace(p,{**scalar,**data,'#'+contract.group:'','/'+contract.group:''})
                    row.addprevious(clone)
                row.getparent().remove(row)
        for p in paragraphs(tree):_replace(p,scalar)
        if (snapshot.get('source') or {}).get('job_snapshot',{}).get('review_route')=='records_manager_only':
            # The approved Manager Only interpretation changes the assignee's
            # duty label. Keep the controlled placeholder contract unchanged.
            for node in tree.findall('.//w:t',NS):
                if node.text:node.text=node.text.replace('Assigned Records Officer','Assigned Records Manager').replace('مسؤول الوثائق المكلّف','مدير الوثائق المكلّف')
        if '{{' in paragraph_text(tree) or '}}' in paragraph_text(tree):invalid('disposition_document_snapshot_invalid')
        values[name]=etree.tostring(tree,xml_declaration=True,encoding='UTF-8',standalone=True)
    stream=BytesIO()
    with ZipFile(stream,'w',ZIP_DEFLATED) as archive:
        for name,value in values.items():
            info=ZipInfo(name,date_time=(1980,1,1,0,0,0));info.compress_type=ZIP_DEFLATED
            archive.writestr(info,value)
    return stream.getvalue()


def verify_pdf(content):
    from pypdf import PdfReader
    try:
        reader=PdfReader(BytesIO(content),strict=True)
        if reader.is_encrypted or not reader.pages:invalid('disposition_document_render_failed',409)
        found=False
        def check_resources(resources,seen):
            nonlocal found
            if not resources:return
            for font in resources.get('/Font',{}).values():
                font=font.get_object()
                for f in font.get('/DescendantFonts',[font]):
                    f=f.get_object();name=str(f.get('/BaseFont',font.get('/BaseFont','')))
                    descriptor=f.get('/FontDescriptor')
                    if 'changa' not in name.casefold() or descriptor is None:invalid('disposition_template_changa_required',409)
                    descriptor=descriptor.get_object()
                    if not any(k in descriptor for k in ('/FontFile','/FontFile2','/FontFile3')):invalid('disposition_template_changa_required',409)
                    found=True
            for x in resources.get('/XObject',{}).values():
                identity=(getattr(x,'idnum',id(x)),getattr(x,'generation',0))
                if identity in seen:continue
                seen.add(identity);check_resources(x.get_object().get('/Resources'),seen)
        for page in reader.pages:check_resources(page.get('/Resources'),set())
        if not found:invalid('disposition_template_changa_required',409)
        return len(reader.pages)
    except HTTPException:raise
    except Exception:invalid('disposition_document_render_failed',409)


def render(content,kind,snapshot,settings):
    filled=fill(content,kind,snapshot,settings['MAX_RENDITION_SIZE_BYTES'])
    with tempfile.TemporaryDirectory(prefix='wathiq-disposition-') as temporary:
        root=Path(temporary);source=root/'document.docx';source.write_bytes(filled)
        profile=root/'profile';profile.mkdir()
        fonts=root/'fonts.conf'
        fonts.write_text('<fontconfig><dir>'+escape(str(FONT_DIRECTORY))+'</dir><cachedir>'+escape(str(root/'font-cache'))+'</cachedir></fontconfig>')
        (profile/'user').mkdir()
        (profile/'user'/'registrymodifications.xcu').write_text('''<?xml version="1.0"?><oor:items xmlns:oor="http://openoffice.org/2001/registry"><item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop></item><item oor:path="/org.openoffice.Office.Writer/Content/Update"><prop oor:name="Link" oor:op="fuse"><value>2</value></prop></item></oor:items>''')
        try:
            conversion=subprocess.run([_libreoffice_binary(),'--headless','--nologo','--nodefault','--nolockcheck','--norestore',
              '-env:UserInstallation='+profile.as_uri(),'--convert-to','pdf:writer_pdf_Export','--outdir',str(root),str(source)],
              capture_output=True,timeout=settings['DOCUMENT_CONVERSION_TIMEOUT_SECONDS'],
              env={**os.environ,'FONTCONFIG_FILE':str(fonts),'SAL_DISABLE_OPENCL':'1'})
            target=root/'document.pdf'
            if conversion.returncode or not target.is_file():invalid('disposition_document_render_failed',409)
            if target.stat().st_size>settings['MAX_RENDITION_SIZE_BYTES']:invalid('disposition_template_size',413)
            pdf=target.read_bytes();pages=verify_pdf(pdf)
            return pdf,{'renderer':'LibreOffice Writer PDF export','pages':pages,'filled_docx_sha256':sha256(filled).hexdigest()}
        except (ConversionUnavailable,OSError,subprocess.TimeoutExpired):invalid('disposition_document_renderer_unavailable',503)
