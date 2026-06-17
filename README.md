# PDF MCP Server 📄✨

PDF MCP server that gives Claude Code and other MCP-compatible AI assistants the ability to create, edit, design, and manipulate PDF documents with professional-grade design capabilities.

PDF MCP allows AI agents to:

* Create stunning cover pages, certificates, and invoices
* Generate gradient backgrounds and glassmorphism cards
* Build infographics, timelines, and data charts
* Design resumes, brochures, and magazine-style layouts
* Merge, split, rotate, compress, and encrypt PDFs
* Extract text, tables, and images from PDFs
* Add watermarks, page numbers, QR codes, and stamps
* Apply geometric patterns and visual effects
* Build multi-page documents page by page
* Automate document generation workflows

---

## Features

### 🎨 Professional Design Tools

* **Cover Pages** - 5 styles: diagonal, split, centered, minimal, bold
* **Gradients** - Linear, horizontal, and radial gradients
* **Glassmorphism Cards** - Modern card-based layouts with blur effects
* **Hero Sections** - Landing page style with call-to-action buttons
* **Timelines** - Vertical infographic timelines with events
* **Infographics** - Data visualization with horizontal and circular bars
* **Certificates** - Formal achievement certificates with decorative borders
* **Invoices** - Professional invoices with itemized line items
* **Resumes** - Two-column modern resume layout
* **Brochures** - Multi-column magazine-style pages
* **Charts** - Bar and line charts with custom data
* **Tables** - Styled data tables with headers and alternating rows

### 📐 Page Management

* **Page Creation** - Create single or multi-page PDFs
* **Append Pages** - Add pages to the end
* **Replace Pages** - Replace specific page slots
* **Reordering** - Reorder pages with custom sequences
* **Delete Pages** - Remove specific pages
* **Page Info** - Get dimensions, rotation, and crop box details

### ✏️ Text & Typography

* **Word Wrapping** - Automatic text wrapping - never cut off
* **Multiple Fonts** - Helvetica, Times-Roman, Courier variants
* **Alignment** - Left, center, right, and justified text
* **Text Annotations** - Overlay text at any position with rotation
* **Rich Headers** - Title, subtitle, and body text support

### 🎯 Standard PDF Operations

* **Merge** - Combine multiple PDFs into one
* **Split** - Split into individual pages or ranges
* **Rotate** - Rotate pages by 90°, 180°, or 270°
* **Compress** - Reduce file size by deduplication
* **Encrypt/Decrypt** - Password protect or remove protection
* **Extract** - Extract text, tables, and images
* **Crop** - Trim margins from pages
* **Flatten** - Flatten form fields into static content

### 🖼️ Visual Enhancements

* **Watermarks** - Diagonal text watermarks with opacity control
* **Page Numbers** - Centered, right, left, or footer bar styles
* **QR Codes** - Embed QR codes with optional labels
* **Stamps** - "APPROVED", "REJECTED", "DRAFT" stamps
* **Geometric Backgrounds** - Hexagons, triangles, dots, lines, waves, circuit
* **Images** - Embed images at any position and size
* **Gradients** - Linear and radial gradient backgrounds
* **Shapes** - Rounded rectangles, circles, and arcs

### ⚙️ Metadata & Info

* **Get Metadata** - Title, author, subject, creator, dates
* **Set Metadata** - Update all standard metadata fields
* **PDF Info** - Page count, dimensions, encryption status
* **Page Info** - Detailed per-page information

---

## Requirements

Before using PDF MCP, ensure you have:

* Python 3.8+
* Required Python packages (automatically installed)

### Dependencies

```txt
mcp[cli]
PyPDF2>=3.0.0
pdfplumber>=0.10.0
Pillow>=10.0.0
reportlab>=4.0.0
qrcode>=7.0.0
```

---

## Installation

Clone the repository:

```bash
git clone https://github.com/IMApurbo/pdfmcp.git
cd pdfmcp
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Install PDF MCP:

```bash
pip install .
```

Verify installation:

```bash
python server.py --help
```

---

## Claude Code Setup

Add PDF MCP to Claude Code:

```bash
claude mcp add pdfmcp -- python server.py
```

If PDF MCP is installed in a custom Python environment, use that environment's Python executable:

### Find your Python path

Linux/macOS:

```bash
which python
```

Windows:

```powershell
where python
```

Then configure Claude Code:

```bash
claude mcp add pdfmcp -- <python-path> server.py
```

Example:

```bash
claude mcp add pdfmcp -- /home/user/miniconda3/envs/pdfmcp/bin/python server.py
```

Verify:

```bash
claude mcp list
```

---

## Quick Start Guide

### Step 1: Set Your Current PDF

```text
Set current PDF to /path/to/my_document.pdf
```

### Step 2: Create a Cover Page

```text
Create a cover page with title "My Report", subtitle "Annual 2025", style "diagonal"
```

### Step 3: Add Content Pages

```text
Create a text page with title "Introduction", content "This is the introduction text..."
```

### Step 4: Add Visual Elements

```text
Add a geometric background with hexagons to my current PDF
```

### Step 5: Finalize

```text
Add page numbers in footer bar style to my current PDF
```

---

## Example Usage

### Create a Multi-Page Report

```text
Create a new or modify file /reports/annual_report.pdf with mode "new"
Add a cover page with title "Annual Report 2025", style "bold"
Create a table page with headers ["Quarter", "Revenue", "Growth"] and data from CSV
Create a chart page with bar chart showing quarterly data
Add page numbers in footer bar style
```

### Design a Certificate

```text
Create a certificate for "Alice Johnson", title "Employee of the Year", issuer "CEO Office"
```

### Generate an Invoice

```text
Create an invoice for company "Tech Solutions", client "Acme Corp", items:
[
  {"desc": "Consulting", "qty": 10, "rate": 150},
  {"desc": "Software License", "qty": 2, "rate": 500}
]
```

### Build a Resume

```text
Create a resume for "Jane Doe", job title "Software Engineer", with summary, experience, skills, and education
```

### Extract Data from PDF

```text
Extract all tables from my current PDF and save as JSON
```

### Add Watermark

```text
Add watermark "CONFIDENTIAL" to my current PDF with 20% opacity
```

### Extract Text

```text
Extract text from pages 1-5 of my current PDF
```

### Add QR Code

```text
Add QR code linking to https://example.com on page 1 at position x=460, y=30
```

### Create Brochure

```text
Create a 3-column brochure with headline "Our Services" and 6 section cards
```

### Generate Infographic

```text
Create an infographic with statistics: Sales 85%, Marketing 70%, R&D 95%, Support 60%
```

### Design Timeline

```text
Create a timeline with events:
2023: Company founded
2024: First product launch
2025: Global expansion
```

### Add Geometric Pattern

```text
Add a circuit pattern background to all pages of my PDF
```

---

## Working with the Current PDF

PDF MCP implements a **current PDF** system for seamless workflows:

* `set_current_pdf("/path/to/file.pdf")` - Set the working file
* All tools automatically use the current PDF when paths are empty
* `create_new_or_modify()` - Declare and optionally reset your working file

### Example Workflow

```text
# Declare your working file
create new or modify file /reports/quarterly.pdf mode "new"

# Create pages (no need to specify paths)
create cover page with title "Quarterly Report", style "diagonal"
create text page with content "Financial results..."
create chart page showing revenue data

# Finalize
add page numbers with style "footer_bar"
```

---

## Page Parameter Usage

All design/create tools support flexible page positioning:

* **page=1** → Replace/create page 1
* **page=5** → Replace/create page 5 (pads with blank pages if needed)
* **page="append"** → Always add as the last page

### Building Multi-Page Documents

```text
# Create page 1
create cover page page=1

# Append a page
create text page page="append"

# Replace page 2
create table page page=2
```

---

## Design Tools Reference

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `create_cover_page` | Stunning cover pages | style, title, subtitle, bg colors |
| `create_gradient_page` | Gradient backgrounds | color1, color2, direction |
| `create_card_page` | Glassmorphism info cards | cards JSON, columns |
| `create_hero_section` | Landing page style | heading, body, cta_text, bg_style |
| `create_timeline_page` | Vertical timeline | events JSON |
| `create_infographic_page` | Data visualization | stats JSON, bar_style |
| `create_certificate` | Formal certificates | recipient_name, title, issuer |
| `create_invoice` | Professional invoices | company_name, items JSON |
| `create_resume` | Two-column resume | name, experience, skills, education |
| `create_brochure_page` | Multi-column brochure | sections JSON, columns |
| `create_text_page` | Typography-focused | content, font, alignment |
| `create_table_page` | Data tables | headers JSON, rows JSON |
| `create_chart_page` | Bar/line charts | data JSON, chart_type |

---

## Standard Tools Reference

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `pdf_merge` | Merge multiple PDFs | input_paths JSON |
| `pdf_split` | Split into single pages | prefix, output_dir |
| `pdf_split_range` | Extract page range | start_page, end_page |
| `pdf_rotate` | Rotate pages | angle, pages |
| `pdf_compress` | Compress PDF | - |
| `pdf_encrypt` | Password protect | user_password, owner_password |
| `pdf_decrypt` | Remove password | password |
| `pdf_extract_text` | Extract text | pages, output_txt |
| `pdf_extract_tables` | Extract tables | output_json |
| `pdf_extract_images` | Extract images | output_dir, format |
| `pdf_metadata_get` | Get metadata | - |
| `pdf_metadata_set` | Set metadata | title, author, etc. |
| `pdf_reorder_pages` | Reorder pages | order JSON |
| `pdf_delete_pages` | Delete pages | pages_to_delete JSON |
| `pdf_replace_page` | Replace one page | page_number, replacement_pdf |
| `pdf_crop` | Crop margins | left, right, top, bottom |
| `pdf_flatten` | Flatten forms | - |
| `pdf_page_info` | Page details | page_number |
| `pdf_images_to_pdf` | Convert images | image_paths JSON |

---

## Overlay & Enhancement Tools

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `add_watermark` | Text watermark | watermark_text, opacity, angle |
| `add_page_numbers` | Page numbers | style, prefix, start_number |
| `add_qr_code` | QR code overlay | url, page_number, size |
| `pdf_add_header_footer` | Header/footer | header, footer, {page} token |
| `pdf_add_image_to_page` | Embed image | image_path, position, size |
| `pdf_add_text_annotation` | Overlay text | text, position, rotation |
| `pdf_stamp` | Add stamp | stamp_text, color, opacity |
| `add_geometric_background` | Pattern background | pattern, overlay_on_existing |

---

## Server Control Tools

| Tool | Description |
|------|-------------|
| `set_current_pdf` | Set the working PDF file |
| `get_current_pdf` | Get the current PDF path |
| `create_new_or_modify` | Declare working file with mode |

---

## Troubleshooting

### Tool Not Found

Verify Claude Code configuration:

```bash
claude mcp list
```

### Text Not Wrapping Properly

All text rendering uses `_draw_text_block()` for automatic word wrapping. If text appears cut off, check the `max_width` and `max_lines` parameters.

### PDF Operations Failing

Check file permissions and ensure the PDF exists. Use `pdf_info` to verify file integrity.

### Current PDF Not Set

All tools require either an explicit path or a current PDF set via `set_current_pdf()`. Use `get_current_pdf()` to check.

### Temporary File Cleanup

All tools use `TemporaryDirectory()` for intermediate files and automatically delete them on exit - no manual cleanup required.

### Logging

Check the log file at the same directory as the server:

```text
pdf_mcp.log
```

Logs include:
* Tool execution details
* Error traces
* Operation success/failure
* Performance metrics

---

## Advanced Tips

### In-Place Editing

Leave `output_path` empty and tools will overwrite the current PDF:

```text
set current PDF /documents/report.pdf
add watermark "DRAFT" opacity 0.15  # modifies report.pdf in place
```

### Building Page by Page

Use `page="append"` to add pages and `page=N` to update specific pages. Use the same `output_path` to build gradually.

### Text Formatting

All text tools support:
* Multi-line text with `\n`
* Automatic word wrapping
* Max lines to prevent overflow
* Multiple alignment options

### Color Customization

Colors can be specified as:
* Hex strings: `#ff6b6b`, `#667eea`
* CSS color names (limited support)

### Performance Considerations

* Large PDFs may take time for compression
* Image extraction on large files can be memory intensive
* Use page range extraction for large documents when possible

---

## Repository

GitHub:

https://github.com/IMApurbo/pdfmcp

---

## License

MIT License

---

## Disclaimer

PDF MCP is intended for document creation, editing, and automation on documents you own or are authorized to modify. Features that extract content, modify existing documents, or generate professional documents should only be used with appropriate authorization and user consent. Users are responsible for complying with applicable laws, policies, privacy requirements, and security obligations regarding document handling and data processing.
