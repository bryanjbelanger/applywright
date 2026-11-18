import pypdfium2 as pdfium
import os


def render_pages(pdf_path, output_dir, prefix):
    pdf = pdfium.PdfDocument(pdf_path)
    generated_pngs = []
    for i in range(len(pdf)):
        page = pdf.get_page(i)
        image = page.render(scale=2).to_pil()
        out_path = os.path.join(output_dir, f"{prefix}-page-{i+1}.png")
        image.save(out_path)
        generated_pngs.append(out_path)
    return generated_pngs
