"""Author the approved collection-location layout; retain issued v1 unchanged."""
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile,ZipInfo,ZIP_DEFLATED
import sys

from docx import Document
from docx.shared import Pt
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.build_disposition_templates import paragraph,table,prop
from backend.services.api.disposition.template_contract import CONTRACTS


def value(host,key,size=10):
    return paragraph(host,'{{'+key+'}}',size=size)


def main():
    directory=ROOT/'templates/disposition/destruction'
    doc=Document(directory/'physical-preparation-report.default.v1.docx')
    for node in list(doc.element.body):
        if node.tag!=qn('w:sectPr'):doc.element.body.remove(node)
    c=CONTRACTS['physical_preparation_report']
    name=value(doc,'organization.name',16)
    name.paragraph_format.keep_with_next=True
    name.paragraph_format.space_after=Pt(6)
    for run in name.runs:
        run.bold=True;prop(run._r.get_or_add_rPr(),'bCs',val=1)
    paragraph(doc,c.arabic,rtl=True,style='Title',size=19)
    paragraph(doc,c.english,style='Subtitle',size=12).paragraph_format.space_after=Pt(8)
    metadata=table(doc,[61,86,27]);row=metadata.add_row()
    prop(row._tr.get_or_add_trPr(),'cantSplit',val=1)
    for cell,key in zip(row.cells,('job.number','report.generated_at','report.version')):
        cell._tc.remove(cell.paragraphs[0]._p)
        label=c.fields[key]
        paragraph(cell,label[0],rtl=True,size=8)
        paragraph(cell,label[1],size=7)
        value(cell,key,10)
    value(doc,'report.owner',9).paragraph_format.space_after=Pt(8)
    paragraph(doc,'الملفات المطلوب جمعها',rtl=True,style='Heading 1',size=13)
    paragraph(doc,'Aggregations to collect',style='Heading 2',size=10)
    t=table(doc,[14,80,80]);header=t.add_row();prop(header._tr.get_or_add_trPr(),'tblHeader',val=1)
    for cell,label in zip(header.cells,[('تسلسل','No.'),('الملف','Aggregation'),('الموقع الحالي','Current location')]):
        cell._tc.remove(cell.paragraphs[0]._p);prop(cell._tc.get_or_add_tcPr(),'shd',fill='EEF7FD')
        paragraph(cell,label[0],rtl=True,size=9);paragraph(cell,label[1],size=8)
    row=t.add_row();prop(row._tr.get_or_add_trPr(),'cantSplit',val=1)
    for cell in row.cells:
        cell.vertical_alignment=WD_CELL_VERTICAL_ALIGNMENT.TOP
        cell._tc.remove(cell.paragraphs[0]._p)
    serial,identity,location=row.cells
    paragraph(serial,'{{#aggregations}}',size=1)
    # A standalone group token creates a full-width heading when its value changes.
    value(serial,'aggregation.collection_group',10)
    value(serial,'aggregation.serial_number',10).alignment=WD_ALIGN_PARAGRAPH.CENTER
    value(identity,'aggregation.identifier',10)
    value(identity,'aggregation.title',10)
    paragraph(identity,'{{aggregation.classification_code}} · {{aggregation.medium}}',size=8)
    value(identity,'aggregation.owner_note',8)
    value(location,'aggregation.current_location',10)
    value(location,'aggregation.assigned_note',8)
    paragraph(location,'{{/aggregations}}',size=1)
    value(doc,'report.summary',9).paragraph_format.space_before=Pt(8)
    footer=doc.sections[0].footer
    for p in list(footer._element):footer._element.remove(p)
    p=paragraph(footer,'{{job.number}} · {{report.version}} · ',size=8)
    p.alignment=WD_ALIGN_PARAGRAPH.CENTER
    for instruction,separator in [('PAGE',' / '),('NUMPAGES','')]:
        field=OxmlElement('w:fldSimple');field.set(qn('w:instr'),instruction);p._p.append(field)
        if separator:p.add_run(separator).font.name='Changa'
    doc.core_properties.title=c.english;doc.core_properties.subject=c.arabic
    # The retained styles have generous heading spacing. This working guide
    # uses compact explicit leading without fixed-height table rows.
    for p in doc.element.xpath('.//w:p'):
        paragraph_object=Paragraph(p,doc)
        sizes=[r.font.size.pt for r in paragraph_object.runs if r.font.size]
        paragraph_object.paragraph_format.space_before=Pt(0)
        paragraph_object.paragraph_format.line_spacing=Pt(max(sizes or [10])*1.4)
    package=BytesIO();doc.save(package)
    with ZipFile(package) as source,ZipFile(directory/c.filename,'w',ZIP_DEFLATED) as out:
        for name in source.namelist():
            info=ZipInfo(name,date_time=(1980,1,1,0,0,0));info.compress_type=ZIP_DEFLATED
            out.writestr(info,source.read(name))
    print(directory/c.filename)


if __name__=='__main__':main()
