"""Generate full-length companion fixtures once; reuse the same bytes in both trials."""

import argparse
from pathlib import Path
import shutil

from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from pptx import Presentation
from pptx.util import Inches


def generate(docx, directory):
    directory.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(docx, directory / "benchmark.docx")
    book = Workbook()
    book.remove(book.active)
    for index in range(40):
        sheet = book.create_sheet(f"Branch {index + 1}")
        sheet.append(["Branch", "Quarter", "Plan", "Actual", "Variance"])
        for row in range(2, 32):
            sheet.append(
                [index + 1, row - 1, 3000 + row, 50 * (index + row), f"=D{row}-C{row}"]
            )
        chart = BarChart()
        chart.add_data(
            Reference(sheet, min_col=3, max_col=4, min_row=1, max_row=12),
            titles_from_data=True,
        )
        sheet.add_chart(chart, "G2")
        sheet.print_area = "A1:Q32"
        sheet.sheet_properties.pageSetUpPr.fitToPage = True
        sheet.page_setup.fitToWidth = sheet.page_setup.fitToHeight = 1
        sheet.page_setup.orientation = "landscape"
    book.save(directory / "benchmark.xlsx")
    deck = Presentation()
    for index in range(60):
        slide = deck.slides.add_slide(deck.slide_layouts[5])
        slide.shapes.title.text = f"Operating review — site {index + 1}"
        table = slide.shapes.add_table(
            13, 4, Inches(0.6), Inches(1.5), Inches(8.8), Inches(5.4)
        ).table
        for column, label in enumerate(("Quarter", "Budget", "Actual", "Variance")):
            table.cell(0, column).text = label
        for row in range(1, 13):
            budget, actual = 3000 + row, 50 * (row + index)
            for column, value in enumerate((row, budget, actual, actual - budget)):
                table.cell(row, column).text = str(value)
    deck.save(directory / "benchmark.pptx")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("docx", type=Path)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    generate(args.docx, args.directory)
