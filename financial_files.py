"""Bounded CSV/XLSX ingestion without filesystem extraction or formula evaluation.

Only values in one explicitly named (or first visible) worksheet are converted
to CSV. This is a file reader, not a claim of coverage for every bank/exporter.
"""
from __future__ import annotations

import base64
import binascii
import csv
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
import io
import posixpath
import re
import stat
from threading import BoundedSemaphore
import zipfile
from xml.etree import ElementTree as ET


MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_EXPANDED_BYTES = 8 * 1024 * 1024
MAX_WORKSHEET_ROWS = 5000
MAX_COLUMNS = 80
MAX_CELLS = 100_000
MAX_XML_NODES = 300_000
FILE_PARSE_SLOT = BoundedSemaphore(1)
NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
REL_NS = 'http://schemas.openxmlformats.org/package/2006/relationships'
DOC_REL_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'


class FinancialFileError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _xml(raw):
    try:
        text = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        raise FinancialFileError('XLSX 内部 XML 编码不支持，请重新另存为标准 XLSX 或 CSV') from None
    if re.search(r'<!\s*(?:DOCTYPE|ENTITY)\b', text, re.I):
        raise FinancialFileError('文件含不支持的 XML 声明，未读取账单')
    depth, nodes = 0, 0
    try:
        parser = ET.iterparse(io.StringIO(text), events=('start', 'end'))
        for event, _ in parser:
            if event == 'start':
                depth += 1
                nodes += 1
                if depth > 48 or nodes > MAX_XML_NODES:
                    raise FinancialFileError('工作簿结构过于复杂，请按月份拆分')
            else:
                depth -= 1
        return parser.root
    except ET.ParseError:
        raise FinancialFileError('XLSX 内部 XML 损坏，请重新导出') from None


def _plain_text(node):
    if node is None:
        return ''
    # Include actual rich text, excluding optional phonetic annotations.
    parts = [part.text or '' for part in node.findall(f'{{{NS}}}t')]
    parts += [part.text or '' for part in node.findall(f'{{{NS}}}r/{{{NS}}}t')]
    value = ''.join(parts)
    if len(value) > 20_000:
        raise FinancialFileError('单元格文本过长，请整理后再导入')
    return value


def _date_style(code):
    code = re.sub(r'"[^"]*"|\\.|\[[^\]]*\]', '', code.lower())
    return bool(re.search(r'[ymdhs]', code))


def _excel_date(value, epoch1904):
    try:
        serial = Decimal(value)
        if not serial.is_finite() or not 0 <= serial <= 73050:
            raise FinancialFileError('日期序列超出支持范围，请检查 Excel 日期格式')
        if epoch1904:
            base = datetime(1904, 1, 1)
        else:
            base = datetime(1899, 12, 30)
            if 0 < serial < 60:
                serial += 1
        converted = base + timedelta(days=float(serial))
        return converted.strftime('%Y-%m-%d %H:%M:%S') if serial % 1 else converted.strftime('%Y-%m-%d')
    except (InvalidOperation, OverflowError, ValueError):
        raise FinancialFileError('Excel 日期单元格无效') from None


def _read_xlsx(raw, requested_sheet, *, inspect_sheets=False, include_structure=False):
    if raw.startswith(bytes.fromhex('D0CF11E0A1B11AE1')):
        raise FinancialFileError('不支持加密工作簿或旧版 XLS；请解密并另存为 XLSX 或 CSV')
    if not isinstance(requested_sheet, str) or len(requested_sheet) > 100:
        raise FinancialFileError('工作表名称不正确')
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except (zipfile.BadZipFile, OSError, ValueError):
        raise FinancialFileError('文件不是可读的 XLSX 工作簿') from None
    with archive:
        members = archive.infolist()
        if len(members) > 128 or sum(item.file_size for item in members) > MAX_EXPANDED_BYTES:
            raise FinancialFileError('工作簿展开后超过 8 MB 或内容过多，请按月份拆分')
        names = set()
        for member in members:
            name = member.filename
            original_name = member.orig_filename
            parts = name.split('/')
            lower = name.lower()
            if original_name != name or '\x00' in original_name or name.startswith('/') or '\\' in name or any(part in {'.', '..'} for part in parts) or ':' in name:
                raise FinancialFileError('工作簿包含不安全的内部路径')
            if lower in names:
                raise FinancialFileError('工作簿含重复内部文件，无法确定数据来源')
            names.add(lower)
            if member.flag_bits & 1:
                raise FinancialFileError('不支持加密 XLSX，请先在本机解密')
            if member.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                raise FinancialFileError('工作簿压缩格式不支持')
            if stat.S_ISLNK(member.external_attr >> 16):
                raise FinancialFileError('工作簿包含不安全的内部链接')
            if any(word in lower for word in ('vbaproject', 'macrosheet', 'externallink', 'activex', 'embeddings/')) or lower.endswith('.bin'):
                raise FinancialFileError('不支持含宏、外部链接或嵌入对象的工作簿，请导出纯值 XLSX / CSV')

        def read(name, required=True):
            try:
                info = archive.getinfo(name)
            except KeyError:
                if not required:
                    return None
                raise FinancialFileError('XLSX 缺少必要的内部文件') from None
            try:
                with archive.open(info) as stream:
                    value = stream.read(min(info.file_size + 1, MAX_EXPANDED_BYTES + 1))
                if len(value) != info.file_size or len(value) > MAX_EXPANDED_BYTES:
                    raise FinancialFileError('工作簿内部文件大小不一致')
                return value
            except (zipfile.BadZipFile, RuntimeError, OSError, EOFError):
                raise FinancialFileError('工作簿内容损坏或无法解压') from None

        # Inspect every relationship: no external network/resource references.
        content_types = _xml(read('[Content_Types].xml'))
        types_ns = 'http://schemas.openxmlformats.org/package/2006/content-types'
        for item in content_types:
            if re.search(r'macroenabled|vbaproject|macrosheet', item.attrib.get('ContentType', ''), re.I):
                # Some value-only exporters leave an unused binary Default.
                # OPC Defaults apply by extension; this exact declaration does
                # not describe a part when the package has no .bin member.
                unused_binary_default = (
                    content_types.tag == f'{{{types_ns}}}Types'
                    and item.tag == f'{{{types_ns}}}Default'
                    and item.attrib == {'Extension': 'bin',
                                        'ContentType': 'application/vnd.ms-excel.sheet.binary.macroEnabled.main'}
                    and len(item) == 0 and not (item.text or '').strip()
                    and not any(name.endswith('.bin') for name in names)
                )
                if not unused_binary_default:
                    raise FinancialFileError('工作簿声明了宏内容，请另存为无宏 XLSX 或 CSV')
        rels = {}
        for member in members:
            if member.filename.lower().endswith('.rels'):
                root = _xml(read(member.filename))
                for rel in root:
                    if rel.attrib.get('TargetMode', '').lower() == 'external':
                        raise FinancialFileError('工作簿含外部链接，请删除链接并另存为纯值文件')
                    target = rel.attrib.get('Target', '')
                    if re.match(r'^[A-Za-z][A-Za-z0-9+.-]*:', target) or target.startswith('//') or '\\' in target:
                        raise FinancialFileError('工作簿包含外部资源引用')
                rels[member.filename] = root
        workbook = _xml(read('xl/workbook.xml'))
        properties = workbook.find(f'{{{NS}}}workbookPr')
        epoch1904 = properties is not None and properties.attrib.get('date1904', '').lower() in {'1', 'true'}
        relationships = rels.get('xl/_rels/workbook.xml.rels')
        if relationships is None:
            raise FinancialFileError('工作簿缺少工作表关系')
        targets = {}
        for rel in relationships:
            target = rel.attrib.get('Target', '')
            normalized = posixpath.normpath(target.lstrip('/') if target.startswith('/') else posixpath.join('xl', target))
            if not normalized.startswith('xl/') or '..' in normalized.split('/'):
                raise FinancialFileError('工作表引用超出工作簿范围')
            rid = rel.attrib.get('Id')
            if not rid or rid in targets:
                raise FinancialFileError('工作簿关系标识重复或缺失')
            targets[rid] = (normalized, rel.attrib.get('Type', ''))
        sheets = []
        for sheet in workbook.findall(f'{{{NS}}}sheets/{{{NS}}}sheet'):
            name = sheet.attrib.get('name', '')
            rid = sheet.attrib.get(f'{{{DOC_REL_NS}}}id')
            target, kind = targets.get(rid, ('', ''))
            if not name or len(name) > 100 or not target or not kind.endswith('/worksheet'):
                raise FinancialFileError('工作表信息无效或类型不支持')
            if name in [item['name'] for item in sheets]:
                raise FinancialFileError('工作表名称重复，无法选择账单')
            sheets.append({'name': name, 'state': sheet.attrib.get('state', 'visible'), 'path': target})
        if not sheets or len(sheets) > 20:
            raise FinancialFileError('工作簿须包含 1～20 个普通工作表')
        if inspect_sheets:
            # Discovery does not validate financial cells or issue an import
            # receipt. Still reject malformed/unsafe XML throughout the package.
            inspected = set()
            for member in members:
                if member.filename.lower().endswith('.xml'):
                    _xml(read(member.filename))
                    inspected.add(member.filename)
            for sheet in sheets:
                if sheet['path'] not in inspected:
                    _xml(read(sheet['path']))
            return '', {'format': 'xlsx', 'encoding': 'OOXML / UTF-8', 'sheet': None,
                        'sheets': [sheet['name'] for sheet in sheets], 'worksheetRows': None,
                        'note': '仅列出工作表名称，尚未解析记录或核对单元格。选择账单工作表后再检查金额与预览。'}
        chosen = next((sheet for sheet in sheets if sheet['name'] == requested_sheet), None) if requested_sheet else next((sheet for sheet in sheets if sheet['state'] == 'visible'), None)
        if not chosen:
            raise FinancialFileError('指定工作表不存在或没有可见工作表，请核对名称')

        shared = []
        strings = read('xl/sharedStrings.xml', False)
        if strings:
            for node in _xml(strings).findall(f'{{{NS}}}si'):
                if len(shared) >= MAX_CELLS:
                    raise FinancialFileError('共享文本过多，请拆分工作簿')
                shared.append(_plain_text(node))
        date_styles = set()
        styles = read('xl/styles.xml', False)
        if styles:
            root = _xml(styles)
            codes = {}
            for num_format in root.findall(f'{{{NS}}}numFmts/{{{NS}}}numFmt'):
                codes[num_format.attrib.get('numFmtId')] = num_format.attrib.get('formatCode', '')
            for index, xf in enumerate(root.findall(f'{{{NS}}}cellXfs/{{{NS}}}xf')):
                number = xf.attrib.get('numFmtId', '0')
                if not re.fullmatch(r'\d{1,5}', number):
                    raise FinancialFileError('单元格格式标识无效')
                if int(number) in {*range(14, 23), *range(27, 37), *range(45, 48), *range(50, 59)} or _date_style(codes.get(number, '')):
                    date_styles.add(index)
        root = _xml(read(chosen['path']))
        table, addresses, cell_count = {}, set(), 0
        for row in root.findall(f'{{{NS}}}sheetData/{{{NS}}}row'):
            row_index = row.attrib.get('r', '')
            if not re.fullmatch(r'\d{1,6}', row_index) or not 1 <= int(row_index) <= MAX_WORKSHEET_ROWS or int(row_index) in table:
                raise FinancialFileError('工作表最多 5000 行，且行号须有效且不重复')
            row_index = int(row_index)
            values = []
            for cell in row.findall(f'{{{NS}}}c'):
                cell_count += 1
                if cell_count > MAX_CELLS:
                    raise FinancialFileError('工作表单元格过多，请拆分文件')
                address = cell.attrib.get('r', '')
                match = re.fullmatch(r'([A-Z]{1,3})([1-9]\d{0,5})', address)
                if not match or int(match[2]) != row_index or address in addresses:
                    raise FinancialFileError('单元格坐标缺失、重复或不匹配')
                addresses.add(address)
                col = 0
                for char in match[1]:
                    col = col * 26 + ord(char) - 64
                if col > MAX_COLUMNS:
                    raise FinancialFileError('工作表最多 80 列，请移除无关列')
                if cell.find(f'{{{NS}}}f') is not None:
                    raise FinancialFileError('选定工作表包含公式；请复制为纯值后导入，不读取公式缓存作为账单')
                value = cell.findtext(f'{{{NS}}}v', default='')
                cell_type = cell.attrib.get('t', 'n')
                if cell_type == 'inlineStr':
                    value = _plain_text(cell.find(f'{{{NS}}}is'))
                elif cell_type == 's':
                    if not re.fullmatch(r'\d{1,7}', value) or int(value) >= len(shared):
                        raise FinancialFileError('共享文本引用无效')
                    value = shared[int(value)]
                elif cell_type == 'e':
                    raise FinancialFileError('工作表包含错误单元格，请修正后导入')
                elif cell_type == 'b':
                    value = 'TRUE' if value == '1' else 'FALSE'
                elif cell_type == 'n':
                    style = cell.attrib.get('s', '0')
                    if not re.fullmatch(r'\d{1,5}', style):
                        raise FinancialFileError('单元格样式标识无效')
                    if value and int(style) in date_styles:
                        value = _excel_date(value, epoch1904)
                elif cell_type not in {'str', 'd'}:
                    raise FinancialFileError('工作表包含不支持的单元格类型')
                if len(value) > 20_000 or '\x00' in value:
                    raise FinancialFileError('单元格内容过长或无效')
                if len(values) < col:
                    values += [''] * (col - len(values))
                values[col - 1] = value
            table[row_index] = values
        if not table:
            raise FinancialFileError('所选工作表没有可读的表格数据')
        stream = io.StringIO(newline='')
        writer = csv.writer(stream, lineterminator='\n')
        for index in range(1, max(table) + 1):
            writer.writerow(table.get(index, []))
        content = stream.getvalue()
        if len(content.encode()) > MAX_FILE_BYTES:
            raise FinancialFileError('工作表文本超过 2 MB，请按月份拆分')
        info = {'format': 'xlsx', 'encoding': 'OOXML / UTF-8', 'sheet': chosen['name'],
                'sheets': [sheet['name'] for sheet in sheets], 'worksheetRows': len(table),
                'note': '仅导入所选工作表的纯值；Excel 中已经丢失的长编号精度无法恢复，请在预览中核对原始编号。'}
        if include_structure:
            # Internal opt-in for a source-specific parser, never a client file
            # option. The caller must remove this before returning fileInfo.
            info['_worksheetStructure'] = {
                'rows': table,
                'mergeRefs': [node.get('ref', '') for node in root.findall(f'{{{NS}}}mergeCells/{{{NS}}}mergeCell')],
            }
        return content, info


def _read_financial_file(file, *, inspect_sheets=False, include_structure=False):
    if not isinstance(file, dict) or set(file) - {'name', 'contentBase64', 'encoding', 'sheet'}:
        raise FinancialFileError('文件字段不正确')
    name = file.get('name')
    encoded = file.get('contentBase64')
    if not isinstance(name, str) or not 1 <= len(name) <= 200 or '\x00' in name:
        raise FinancialFileError('请提供有效的文件名')
    if not isinstance(encoded, str) or not encoded or len(encoded) > ((MAX_FILE_BYTES + 2) // 3) * 4:
        raise FinancialFileError('文件最多 2 MB，请按月份拆分')
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise FinancialFileError('文件编码无效，请重新选择文件') from None
    if not raw or len(raw) > MAX_FILE_BYTES:
        raise FinancialFileError('文件为空或超过 2 MB')
    safe_name = re.split(r'[/\\]', name)[-1]
    suffix = safe_name.rsplit('.', 1)[-1].lower() if '.' in safe_name else ''
    if inspect_sheets and suffix != 'xlsx':
        raise FinancialFileError('工作表列表仅适用于 XLSX 文件')
    if suffix in {'xls', 'xlsm', 'xlsb', 'xltm'}:
        raise FinancialFileError('不支持旧版 XLS、宏或二进制工作簿；请另存为无公式 XLSX 或 CSV')
    if suffix == 'xlsx':
        text, info = _read_xlsx(raw, file.get('sheet', ''), inspect_sheets=inspect_sheets, include_structure=include_structure)
    elif suffix in {'csv', 'txt'}:
        encoding = file.get('encoding', 'auto')
        if not isinstance(encoding, str) or encoding not in {'auto', 'utf-8', 'gb18030'}:
            raise FinancialFileError('编码应为自动、UTF-8 或 GB18030')
        encodings = ['utf-8-sig', 'gb18030'] if encoding == 'auto' else ['utf-8-sig' if encoding == 'utf-8' else encoding]
        text = None
        for candidate in encodings:
            try:
                text = raw.decode(candidate, errors='strict')
                detected = 'UTF-8' if candidate == 'utf-8-sig' else 'GB18030'
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            raise FinancialFileError('无法按所选编码读取，请改用 UTF-8 / GB18030 或重新导出文件')
        if '\x00' in text or '\ufffd' in text:
            raise FinancialFileError('文件含乱码或不支持的二进制内容，请重新导出 CSV')
        info = {'format': 'csv', 'encoding': detected, 'sheet': None, 'sheets': [],
                'note': '编码只影响读取；来源、币种、金额和收支方向仍需在预览中核对。'}
    else:
        raise FinancialFileError('请选择 CSV、TXT 或无宏 XLSX 文件')
    info['name'] = safe_name
    return text, info


def read_financial_file(file, *, inspect_sheets=False, include_structure=False):
    if type(inspect_sheets) is not bool:
        raise FinancialFileError('工作表读取模式必须为布尔值')
    if type(include_structure) is not bool:
        raise FinancialFileError('工作表结构读取模式必须为布尔值')
    if not FILE_PARSE_SLOT.acquire(blocking=False):
        raise FinancialFileError('正在处理另一份账单文件，请稍后重试', 429)
    try:
        return _read_financial_file(file, inspect_sheets=inspect_sheets, include_structure=include_structure)
    finally:
        FILE_PARSE_SLOT.release()
