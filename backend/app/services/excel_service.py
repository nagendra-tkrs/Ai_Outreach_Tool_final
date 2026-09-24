import io
import openpyxl
from app.utils.validators import (
    REQUIRED_COLUMNS,
    OPTIONAL_COLUMNS,
    normalize_website,
    normalize_company_name,
    validate_row
)
from app.config.database import get_db

FIELD_MAP = {
    'Company Name': 'companyName',
    'Website': 'website',
    'Industry': 'industry',
    'Country': 'country',
    'Contact Name': 'contactName',
    'Contact Email': 'contactEmail',
    'Revenue': 'revenue',
    'Employee Count': 'employeeCount',
    'Notes': 'notes',
    'Source': 'source'
}

def parse_excel_file(file_bytes: bytes):
    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
    if not wb.sheetnames:
        raise ValueError('Excel file contains no sheets')
    sheet_name = wb.sheetnames[0]
    sheet = wb[sheet_name]

    rows_iter = sheet.iter_rows(values_only=True)
    header_row = next(rows_iter, None)
    if not header_row:
        raise ValueError('Excel file is empty or has no data rows')

    headers = [str(h).strip() if h is not None else "" for h in header_row]

    data = []
    for row in rows_iter:
        if all(cell is None or str(cell).strip() == "" for cell in row):
            continue
        row_dict = {}
        for idx, header in enumerate(headers):
            if header and idx < len(row):
                val = row[idx]
                row_dict[header] = str(val).strip() if val is not None else ""
        data.append(row_dict)

    return {"data": data, "sheetName": sheet_name, "headers": headers}

def validate_headers(headers: list[str]):
    missing = [col for col in REQUIRED_COLUMNS if col not in headers]
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(missing)}")

def normalize_row(raw_row: dict) -> dict:
    normalized = {}
    for header, field in FIELD_MAP.items():
        normalized[field] = raw_row.get(header, "")
    normalized['companyName'] = normalize_company_name(normalized.get('companyName', ''))
    normalized['website'] = (normalized.get('website') or '').strip()
    normalized['normalizedWebsite'] = normalize_website(normalized['website'])
    return normalized

async def process_excel(file_bytes: bytes, original_filename: str) -> dict:
    parsed = parse_excel_file(file_bytes)
    data = parsed["data"]
    headers = parsed["headers"]

    if not data:
        raise ValueError('Excel file is empty or has no data rows')

    validate_headers(headers)

    normalized_rows = []
    for idx, row in enumerate(data):
        norm = normalize_row(row)
        norm['rowNumber'] = idx + 2
        normalized_rows.append(norm)

    seen_names = {}
    seen_websites = {}

    db = get_db()
    existing_website_set = set()
    if db is not None:
        async for comp in db.companies.find({}, {"normalizedWebsite": 1}):
            norm_w = comp.get("normalizedWebsite")
            if norm_w:
                existing_website_set.add(norm_w)

    processed_rows = []
    for row in normalized_rows:
        errors = validate_row(row)
        status = 'invalid' if errors else 'valid'

        if status == 'valid':
            name_lower = row['companyName'].lower()
            if name_lower in seen_names:
                status = 'duplicate_in_file'
                errors.append(f"Duplicate company name (also row {seen_names[name_lower]})")
            else:
                seen_names[name_lower] = row['rowNumber']

        if status == 'valid':
            norm_web = row['normalizedWebsite']
            if norm_web in seen_websites:
                status = 'duplicate_in_file'
                errors.append(f"Duplicate website (also row {seen_websites[norm_web]})")
            else:
                seen_websites[norm_web] = row['rowNumber']

        if status == 'valid' and row['normalizedWebsite'] in existing_website_set:
            status = 'existing_in_db'
            errors.append('Company already exists in database')

        row_data = dict(row)
        row_data['status'] = status
        row_data['validationErrors'] = errors
        processed_rows.append(row_data)

    summary = {
        'total': len(processed_rows),
        'valid': len([r for r in processed_rows if r['status'] == 'valid']),
        'invalid': len([r for r in processed_rows if r['status'] == 'invalid']),
        'duplicates': len([r for r in processed_rows if r['status'] == 'duplicate_in_file']),
        'existingInDb': len([r for r in processed_rows if r['status'] == 'existing_in_db'])
    }

    return {
        'originalFilename': original_filename,
        'summary': summary,
        'rows': processed_rows
    }
