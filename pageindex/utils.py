import tiktoken
import openai
import logging
import os
import re
from datetime import datetime
import time
import json
import PyPDF2
import copy
import asyncio
import pymupdf
from io import BytesIO
import logging
import yaml
from pathlib import Path
from types import SimpleNamespace as config
import textwrap
from pprint import pprint

# Global API configuration - can be set externally
_global_api_key = None
_global_base_url = None

def set_api_config(api_key: str, base_url: str):
    """Set global API configuration"""
    global _global_api_key, _global_base_url
    _global_api_key = api_key
    _global_base_url = base_url

def get_api_key():
    """Get API key from global config or environment"""
    return _global_api_key or os.getenv("INDEX_API_KEY")  # INDEX_API_KEY can be set if you want to use a different key, or use default

def get_base_url():
    """Get base URL from global config or environment"""
    return _global_base_url or os.getenv("INDEX_BASE_URL")  # INDEX_BASE_URL can be set if you want to use a different base URL, or use default

# def count_tokens(text, model=None):
#     if not text:
#         return 0
#     enc = tiktoken.encoding_for_model(model)
#     tokens = enc.encode(text)
#     return len(tokens)

_encoder_cache = {}

def count_tokens(text, model=None):
    if not text:
        return 0
    
    # 清理模型名称（移除 ollama 标签如 :1.7b）
    clean_model = str(model).lower().split(':')[0] if model else 'cl100k_base'
    
    if clean_model in _encoder_cache:
        enc = _encoder_cache[clean_model]
    else:
        # 已知需要 cl100k_base 的模型前缀
        ollama_prefixes = (
            'qwen', 'llama', 'mistral', 'mixtral', 'phi', 
            'gemma', 'deepseek', 'codellama', 'vicuna', 'yi',
            'gpt', 'text-embedding'  # 也包含 OpenAI 模型
        )
        
        # 如果是 Ollama 模型或未知模型，使用 cl100k_base
        if any(clean_model.startswith(prefix) for prefix in ollama_prefixes) or clean_model == 'cl100k_base':
            enc = tiktoken.get_encoding('cl100k_base')
        else:
            try:
                enc = tiktoken.encoding_for_model(model)
            except KeyError:
                enc = tiktoken.get_encoding('cl100k_base')
        _encoder_cache[clean_model] = enc
    
    tokens = enc.encode(text)
    return len(tokens)

def ChatGPT_API_with_finish_reason(model, prompt, api_key=None, base_url=None, chat_history=None):
    max_retries = 10
    api_key = api_key or get_api_key()
    base_url = base_url or get_base_url()
    client = openai.OpenAI(api_key=api_key, base_url=base_url)
    for i in range(max_retries):
        try:
            if chat_history:
                messages = chat_history
                messages.append({"role": "user", "content": prompt})
            else:
                messages = [{"role": "user", "content": prompt}]
            
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0,
            )
            if response.choices[0].finish_reason == "length":
                return response.choices[0].message.content, "max_output_reached"
            else:
                return response.choices[0].message.content, "finished"

        except Exception as e:
            print('************* Retrying *************')
            logging.error(f"Error: {e}")
            if i < max_retries - 1:
                time.sleep(1)
            else:
                logging.error('Max retries reached for prompt: ' + prompt)
                return "Error", "error"


def ChatGPT_API(model, prompt, api_key=None, base_url=None, chat_history=None):
    max_retries = 10
    api_key = api_key or get_api_key()
    base_url = base_url or get_base_url()
    client = openai.OpenAI(api_key=api_key, base_url=base_url)
    for i in range(max_retries):
        try:
            if chat_history:
                messages = chat_history
                messages.append({"role": "user", "content": prompt})
            else:
                messages = [{"role": "user", "content": prompt}]
            
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0,
            )
   
            return response.choices[0].message.content
        except Exception as e:
            print('************* Retrying *************')
            logging.error(f"Error: {e}")
            if i < max_retries - 1:
                time.sleep(1)
            else:
                logging.error('Max retries reached for prompt: ' + prompt)
                return "Error"
            

async def ChatGPT_API_async(model, prompt, api_key=None, base_url=None):
    max_retries = 10
    api_key = api_key or get_api_key()
    base_url = base_url or get_base_url()
    messages = [{"role": "user", "content": prompt}]
    for i in range(max_retries):
        try:
            async with openai.AsyncOpenAI(api_key=api_key, base_url=base_url) as client:
                response = await client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=0,
                )
                return response.choices[0].message.content
        except Exception as e:
            print('************* Retrying *************')
            logging.error(f"Error: {e}")
            if i < max_retries - 1:
                await asyncio.sleep(1)
            else:
                logging.error('Max retries reached for prompt: ' + prompt)
                return "Error"  
            
            
def get_json_content(response):
    start_idx = response.find("```json")
    if start_idx != -1:
        start_idx += 7
        response = response[start_idx:]
        
    end_idx = response.rfind("```")
    if end_idx != -1:
        response = response[:end_idx]
    
    json_content = response.strip()
    return json_content
         

def extract_json(content):
    try:
        # First, try to extract JSON enclosed within ```json and ```
        start_idx = content.find("```json")
        if start_idx != -1:
            start_idx += 7
            end_idx = content.rfind("```")
            json_content = content[start_idx:end_idx].strip()
        else:
            json_content = content.strip()

        json_content = json_content.replace('None', 'null')
        json_content = json_content.replace('\n', ' ').replace('\r', ' ')
        json_content = ' '.join(json_content.split())

        return json.loads(json_content)
    except json.JSONDecodeError as e:
        logging.error(f"Failed to extract JSON: {e}")
        try:
            json_content = json_content.replace(',]', ']').replace(',}', '}')
            return json.loads(json_content)
        except:
            logging.error("Failed to parse JSON even after cleanup")
            return {}
    except Exception as e:
        logging.error(f"Unexpected error while extracting JSON: {e}")
        return {}

def write_node_id(data, node_id=0):
    if isinstance(data, dict):
        data['node_id'] = str(node_id).zfill(4)
        node_id += 1
        for key in list(data.keys()):
            if 'nodes' in key:
                node_id = write_node_id(data[key], node_id)
    elif isinstance(data, list):
        for index in range(len(data)):
            node_id = write_node_id(data[index], node_id)
    return node_id

def get_nodes(structure):
    if isinstance(structure, dict):
        structure_node = copy.deepcopy(structure)
        structure_node.pop('nodes', None)
        nodes = [structure_node]
        for key in list(structure.keys()):
            if 'nodes' in key:
                nodes.extend(get_nodes(structure[key]))
        return nodes
    elif isinstance(structure, list):
        nodes = []
        for item in structure:
            nodes.extend(get_nodes(item))
        return nodes
    
def structure_to_list(structure):
    if isinstance(structure, dict):
        nodes = []
        nodes.append(structure)
        if 'nodes' in structure:
            nodes.extend(structure_to_list(structure['nodes']))
        return nodes
    elif isinstance(structure, list):
        nodes = []
        for item in structure:
            nodes.extend(structure_to_list(item))
        return nodes

    
def get_leaf_nodes(structure):
    if isinstance(structure, dict):
        if not structure['nodes']:
            structure_node = copy.deepcopy(structure)
            structure_node.pop('nodes', None)
            return [structure_node]
        else:
            leaf_nodes = []
            for key in list(structure.keys()):
                if 'nodes' in key:
                    leaf_nodes.extend(get_leaf_nodes(structure[key]))
            return leaf_nodes
    elif isinstance(structure, list):
        leaf_nodes = []
        for item in structure:
            leaf_nodes.extend(get_leaf_nodes(item))
        return leaf_nodes

def is_leaf_node(data, node_id):
    def find_node(data, node_id):
        if isinstance(data, dict):
            if data.get('node_id') == node_id:
                return data
            for key in data.keys():
                if 'nodes' in key:
                    result = find_node(data[key], node_id)
                    if result:
                        return result
        elif isinstance(data, list):
            for item in data:
                result = find_node(item, node_id)
                if result:
                    return result
        return None

    node = find_node(data, node_id)

    if node and not node.get('nodes'):
        return True
    return False

def get_last_node(structure):
    return structure[-1]


def extract_text_from_pdf(pdf_path):
    pdf_reader = PyPDF2.PdfReader(pdf_path)
    text=""
    for page_num in range(len(pdf_reader.pages)):
        page = pdf_reader.pages[page_num]
        text+=page.extract_text()
    return text

def get_pdf_title(pdf_path):
    pdf_reader = PyPDF2.PdfReader(pdf_path)
    meta = pdf_reader.metadata
    title = meta.title if meta and meta.title else 'Untitled'
    return title

def get_text_of_pages(pdf_path, start_page, end_page, tag=True):
    pdf_reader = PyPDF2.PdfReader(pdf_path)
    text = ""
    for page_num in range(start_page-1, end_page):
        page = pdf_reader.pages[page_num]
        page_text = page.extract_text()
        if tag:
            text += f"<start_index_{page_num+1}>\n{page_text}\n<end_index_{page_num+1}>\n"
        else:
            text += page_text
    return text

def get_first_start_page_from_text(text):
    start_page = -1
    start_page_match = re.search(r'<start_index_(\d+)>', text)
    if start_page_match:
        start_page = int(start_page_match.group(1))
    return start_page

def get_last_start_page_from_text(text):
    start_page = -1
    start_page_matches = list(re.finditer(r'<start_index_(\d+)>', text))
    if start_page_matches:
        start_page = int(start_page_matches[-1].group(1))
    return start_page


def sanitize_filename(filename, replacement='-'):
    return filename.replace('/', replacement)

def get_pdf_name(pdf_path):
    """Get PDF filename without extension"""
    if isinstance(pdf_path, str):
        return os.path.splitext(os.path.basename(pdf_path))[0]
    return "unknown"


class JsonLogger:
    def __init__(self, file_path, doc_id=None, progress_callback=None):
        self.file_path = file_path
        self.doc_id = doc_id
        self.progress_callback = progress_callback
        
    def log(self, level, message, **kwargs):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = {
            'timestamp': timestamp,
            'level': level,
            'message': message,
            'doc_id': self.doc_id,
            **kwargs
        }
        # Print to console
        print(json.dumps(log_entry, ensure_ascii=False))
        
        # If it's a progress update and we have a callback, call it
        if level == 'PROGRESS' and self.progress_callback:
            self.progress_callback(log_entry)

    def info(self, message, **kwargs):
        self.log('INFO', message, **kwargs)

    def error(self, message, **kwargs):
        self.log('ERROR', message, **kwargs)

    def debug(self, message, **kwargs):
        self.log('DEBUG', message, **kwargs)

    def exception(self, message, **kwargs):
        self.log('EXCEPTION', message, **kwargs)
        
    def progress(self, current, total, phase, detail=None, **kwargs):
        self.log('PROGRESS', f"Phase: {phase}, {current}/{total}", 
                 current=current, total=total, phase=phase, detail=detail, **kwargs)


def list_to_tree(data):
    def get_parent_structure(structure):
        """Helper function to get the parent structure code"""
        if not structure:
            return None
        parts = str(structure).split('.')
        return '.'.join(parts[:-1]) if len(parts) > 1 else None
    
    # First pass: Create nodes and track parent-child relationships
    nodes = {}
    root_nodes = []
    
    for item in data:
        structure = item.get('structure')
        node = {
            'title': item.get('title'),
            'start_index': item.get('start_index'),
            'end_index': item.get('end_index'),
            'nodes': []
        }
        
        nodes[structure] = node
        
        # Find parent
        parent_structure = get_parent_structure(structure)
        
        if parent_structure:
            # Add as child to parent if parent exists
            if parent_structure in nodes:
                nodes[parent_structure]['nodes'].append(node)
            else:
                root_nodes.append(node)
        else:
            # No parent, this is a root node
            root_nodes.append(node)
    
    # Helper function to clean empty children arrays
    def clean_node(node):
        if not node['nodes']:
            del node['nodes']
        else:
            for child in node['nodes']:
                clean_node(child)
        return node
    
    # Clean and return the tree
    return [clean_node(node) for node in root_nodes]


def add_preface_if_needed(data):
    if not isinstance(data, list) or not data:
        return data

    if data[0]['physical_index'] is not None and data[0]['physical_index'] > 1:
        preface_node = {
            "structure": "0",
            "title": "Preface",
            "physical_index": 1,
        }
        data.insert(0, preface_node)
    return data


def get_page_tokens(file_path, model="gpt-4o-2024-11-20", pdf_parser="PyPDF2", logger=None):
    """Extract pages with token counts from PDF or Markdown"""
    if str(file_path).lower().endswith(".md"):
        # Handle Markdown
        if logger:
            logger.progress(0, 100, "准备页面", detail="正在读取 Markdown 文件...")
            
        if isinstance(file_path, str):
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
        else:
            # BytesIO
            content = file_path.read().decode("utf-8")
        
        # Optimized Markdown splitting logic
        if logger:
            logger.progress(10, 100, "准备页面", detail="正在解析文档大纲...")

        # Split by headers to create more natural boundaries
        # We search for # Header 1 or ## Header 2 etc at the start of lines
        header_sections = re.split(r'(^#+\s+.*)', content, flags=re.MULTILINE)
        
        # re.split with capturing group keeps the delimiters in the list
        # We need to merge them back
        sections = []
        if header_sections[0].strip():
            sections.append(header_sections[0])
            
        for i in range(1, len(header_sections), 2):
            header = header_sections[i]
            body = header_sections[i+1] if i+1 < len(header_sections) else ""
            sections.append(header + body)

        chunks = []
        current_chunk = ""
        current_tokens = 0
        # Increased limit for MD to reduce number of "pages"
        # 2500 tokens is about 3-5 standard pages of text
        max_tokens_per_page = 2500 
        
        total_s = len(sections)
        
        if logger:
            logger.progress(20, 100, "准备页面", detail=f"共有 {total_s} 个章节，正在合并虚拟页面...")

        for i, section in enumerate(sections):
            if not section.strip():
                continue
                
            # For each section, we count tokens
            # Sections are larger than paragraphs, so fewer calls
            s_tokens = count_tokens(section, model)
            
            if current_tokens + s_tokens > max_tokens_per_page and current_chunk:
                chunks.append([current_chunk.strip(), current_tokens])
                current_chunk = section
                current_tokens = s_tokens
            else:
                current_chunk += "\n\n" + section if current_chunk else section
                current_tokens += s_tokens
                
            if logger and i % 5 == 0:
                percent = 20 + int((i / total_s) * 70)
                logger.progress(percent, 100, "准备页面", detail=f"正在合并章节 {i+1}/{total_s}...")
        
        if current_chunk:
            chunks.append([current_chunk.strip(), current_tokens])
            
        if logger:
            logger.progress(100, 100, "准备页面", detail=f"文档解析完成，共生成 {len(chunks)} 个虚拟页面")
            
        return chunks

    if pdf_parser == "PyPDF2":
        if logger:
            logger.progress(0, 100, "准备页面", detail="正在打开 PDF 文件...")
        pdf_reader = PyPDF2.PdfReader(file_path)
        page_list = []
        total_p = len(pdf_reader.pages)
        
        for page_num in range(total_p):
            if logger:
                logger.progress(page_num + 1, total_p, "提取文本", detail=f"正在解析第 {page_num+1}/{total_p} 页...")
            page = pdf_reader.pages[page_num]
            page_text = page.extract_text()
            token_count = count_tokens(page_text, model)
            page_list.append([page_text, token_count])
        return page_list
    else:
        # PyMuPDF
        doc = pymupdf.open(file_path)
        page_list = []
        total_p = len(doc)
        for page_num in range(total_p):
            if logger:
                logger.progress(page_num + 1, total_p, "提取文本", detail=f"正在解析第 {page_num+1}/{total_p} 页...")
            page = doc[page_num]
            page_text = page.get_text()
            token_count = count_tokens(page_text, model)
            page_list.append([page_text, token_count])
        return page_list


def generate_text_image(text, output_path, title=None):
    """Generate a simple image from text (used for Markdown preview)"""
    from PIL import Image, ImageDraw, ImageFont
    import textwrap
    
    # Configuration
    width = 800
    bg_color = (255, 255, 255)
    text_color = (31, 41, 55)
    margin = 40
    line_spacing = 10
    
    # Try to load a font, fallback to default
    try:
        # Try some common fonts on Windows/Linux
        font_paths = [
            "C:/Windows/Fonts/msyh.ttc",  # Microsoft YaHei
            "C:/Windows/Fonts/arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "Arial.ttf"
        ]
        font = None
        for path in font_paths:
            if os.path.exists(path):
                font = ImageFont.truetype(path, 18)
                title_font = ImageFont.truetype(path, 24)
                break
        if not font:
            font = ImageFont.load_default()
            title_font = ImageFont.load_default()
    except:
        font = ImageFont.load_default()
        title_font = ImageFont.load_default()

    # Wrap text
    chars_per_line = 70
    lines = []
    for paragraph in text.split('\n'):
        if not paragraph.strip():
            lines.append("")
            continue
        wrapped = textwrap.wrap(paragraph, width=chars_per_line)
        lines.extend(wrapped)

    # Calculate height
    line_height = font.getbbox("Ay")[3] - font.getbbox("Ay")[1] + line_spacing
    total_height = (len(lines) * line_height) + (margin * 2) + 50 # +50 for title
    
    # Create image
    img = Image.new('RGB', (width, max(total_height, 600)), color=bg_color)
    draw = ImageDraw.Draw(img)
    
    # Draw title
    y = margin
    if title:
        draw.text((margin, y), title, font=title_font, fill=(79, 70, 229))
        y += 40
        draw.line((margin, y, width - margin, y), fill=(226, 232, 240), width=1)
        y += 20
    
    # Draw lines
    for line in lines:
        draw.text((margin, y), line, font=font, fill=text_color)
        y += line_height
        
    img.save(output_path, "JPEG", quality=85)
    return output_path


def get_text_of_pdf_pages(pdf_pages, start_page, end_page):
    """Get text from PDF pages list"""
    text = ""
    for i in range(start_page - 1, end_page):
        if i < len(pdf_pages):
            text += pdf_pages[i][0] + "\n"
    return text


def get_text_of_pdf_pages_with_labels(pdf_pages, start_page, end_page):
    """Get text from PDF pages with labels"""
    text = ""
    for i in range(start_page - 1, end_page):
        if i < len(pdf_pages):
            text += f"<page_{i+1}>\n{pdf_pages[i][0]}\n</page_{i+1}>\n"
    return text


def get_number_of_pages(pdf_path):
    """Get number of pages in PDF"""
    pdf_reader = PyPDF2.PdfReader(pdf_path)
    return len(pdf_reader.pages)


def post_processing(structure, end_physical_index):
    # First convert page_number to start_index in flat list
    for i, item in enumerate(structure):
        item['start_index'] = item.get('physical_index')
        if i < len(structure) - 1:
            if structure[i + 1].get('appear_start') == 'yes':
                item['end_index'] = structure[i + 1]['physical_index']-1
            else:
                item['end_index'] = structure[i + 1]['physical_index']
        else:
            item['end_index'] = end_physical_index
    tree = list_to_tree(structure)
    if len(tree)!=0:
        return tree
    else:
        ### remove appear_start 
        for node in structure:
            node.pop('appear_start', None)
            node.pop('physical_index', None)
        return structure


def clean_structure_post(data):
    if isinstance(data, dict):
        data.pop('page_number', None)
        data.pop('start_index', None)
        data.pop('end_index', None)
        if 'nodes' in data:
            clean_structure_post(data['nodes'])
    elif isinstance(data, list):
        for section in data:
            clean_structure_post(section)
    return data


def remove_fields(data, fields=['text'], max_len=None):
    """Remove specified fields from data"""
    if isinstance(data, dict):
        new_data = {}
        for k, v in data.items():
            if k not in fields:
                if max_len and isinstance(v, str) and len(v) > max_len:
                    v = v[:max_len] + "..."
                new_data[k] = remove_fields(v, fields, max_len)
        return new_data
    elif isinstance(data, list):
        return [remove_fields(item, fields, max_len) for item in data]
    return data


def print_toc(tree, indent=0):
    """Print TOC tree"""
    if isinstance(tree, dict):
        print('  ' * indent + tree.get('title', 'Unknown'))
        if 'nodes' in tree:
            for child in tree['nodes']:
                print_toc(child, indent + 1)
    elif isinstance(tree, list):
        for item in tree:
            print_toc(item, indent)


def print_json(data, max_len=40, indent=2):
    """Print JSON with truncation"""
    def simplify_data(obj):
        if isinstance(obj, dict):
            return {k: simplify_data(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [simplify_data(item) for item in obj]
        elif isinstance(obj, str) and len(obj) > max_len:
            return obj[:max_len] + "..."
        return obj
    
    print(json.dumps(simplify_data(data), indent=indent, ensure_ascii=False))


def remove_structure_text(data):
    """Remove text field from structure"""
    if isinstance(data, dict):
        if 'text' in data:
            del data['text']
        if 'nodes' in data:
            remove_structure_text(data['nodes'])
    elif isinstance(data, list):
        for item in data:
            remove_structure_text(item)


def check_token_limit(structure, limit=110000):
    """Check if structure exceeds token limit"""
    total = 0
    nodes = structure_to_list(structure)
    for node in nodes:
        if 'text' in node:
            total += count_tokens(node['text'])
    return total <= limit


def convert_physical_index_to_int(data):
    if isinstance(data, list):
        for i in range(len(data)):
            if isinstance(data[i], dict) and 'physical_index' in data[i]:
                if isinstance(data[i]['physical_index'], str):
                    if data[i]['physical_index'].startswith('<physical_index_'):
                        data[i]['physical_index'] = int(data[i]['physical_index'].split('_')[-1].rstrip('>').strip())
                    elif data[i]['physical_index'].startswith('physical_index_'):
                        data[i]['physical_index'] = int(data[i]['physical_index'].split('_')[-1].strip())
    elif isinstance(data, str):
        if data.startswith('<physical_index_'):
            data = int(data.split('_')[-1].rstrip('>').strip())
        elif data.startswith('physical_index_'):
            data = int(data.split('_')[-1].strip())
        if isinstance(data, int):
            return data
        else:
            return None
    return data


def convert_page_to_int(data):
    for item in data:
        if 'page' in item and isinstance(item['page'], str):
            try:
                item['page'] = int(item['page'])
            except ValueError:
                pass
    return data


def add_node_text(node, pdf_pages):
    if isinstance(node, dict):
        start_page = node.get('start_index')
        end_page = node.get('end_index')
        node['text'] = get_text_of_pdf_pages(pdf_pages, start_page, end_page)
        if 'nodes' in node:
            add_node_text(node['nodes'], pdf_pages)
    elif isinstance(node, list):
        for index in range(len(node)):
            add_node_text(node[index], pdf_pages)
    return


def add_node_text_with_labels(node, pdf_pages):
    if isinstance(node, dict):
        start_page = node.get('start_index')
        end_page = node.get('end_index')
        node['text'] = get_text_of_pdf_pages_with_labels(pdf_pages, start_page, end_page)
        if 'nodes' in node:
            add_node_text_with_labels(node['nodes'], pdf_pages)
    elif isinstance(node, list):
        for index in range(len(node)):
            add_node_text_with_labels(node[index], pdf_pages)
    return


async def generate_node_summary(node, model=None):
    prompt = f"""You are given a part of a document, your task is to generate a description of the partial document about what are main points covered in the partial document.                                 
    Partial Document Text: {node['text']}
    
    Directly return the description, do not include any other text.
    """
    response = await ChatGPT_API_async(model, prompt)
    return response


async def generate_summaries_for_structure(structure, model=None, logger=None):
    nodes = structure_to_list(structure)
    total_nodes = len(nodes)
    
    if logger:
        logger.progress(0, total_nodes, "生成摘要", detail=f"准备为 {total_nodes} 个节点生成摘要...")
        
    tasks = []
    for i, node in enumerate(nodes):
        tasks.append(generate_node_summary(node, model=model))
        
    # We can use asyncio.as_completed to get progress
    summaries = [None] * total_nodes
    for i, future in enumerate(asyncio.as_completed(tasks)):
        summary = await future
        # Match summary back to task? asyncio.as_completed doesn't preserve order easily
        # Let's just collect and assign at end, but report progress
        if logger:
            logger.progress(i + 1, total_nodes, "生成摘要", detail=f"已完成 {i+1}/{total_nodes} 个节点的摘要生成")
            
    # Re-run properly to preserve order or use a wrapper
    summaries = await asyncio.gather(*tasks)
    
    for node, summary in zip(nodes, summaries):
        node['summary'] = summary
    return structure


def create_clean_structure_for_description(structure):
    """Create a clean structure for document description generation"""
    if isinstance(structure, dict):
        clean_node = {}
        for key in ['title', 'node_id', 'summary', 'prefix_summary']:
            if key in structure:
                clean_node[key] = structure[key]
        
        if 'nodes' in structure and structure['nodes']:
            clean_node['nodes'] = create_clean_structure_for_description(structure['nodes'])
        
        return clean_node
    elif isinstance(structure, list):
        return [create_clean_structure_for_description(item) for item in structure]
    else:
        return structure


def generate_doc_description(structure, model=None):
    prompt = f"""Your are an expert in generating descriptions for a document.
    You are given a structure of a document. Your task is to generate a one-sentence description for the document, which makes it easy to distinguish the document from other documents.                                
    Document Structure: {structure}
    
    Directly return the description, do not include any other text.
    """
    response = ChatGPT_API(model, prompt)
    return response


def reorder_dict(data, key_order):
    if not key_order:
        return data
    return {key: data[key] for key in key_order if key in data}


def format_structure(structure, order=None):
    if not order:
        return structure
    if isinstance(structure, dict):
        if 'nodes' in structure:
            structure['nodes'] = format_structure(structure['nodes'], order)
        if not structure.get('nodes'):
            structure.pop('nodes', None)
        structure = reorder_dict(structure, order)
    elif isinstance(structure, list):
        structure = [format_structure(item, order) for item in structure]
    return structure


class ConfigLoader:
    def __init__(self, default_path: str = None):
        if default_path is None:
            default_path = Path(__file__).parent / "config.yaml"
        self._default_dict = self._load_yaml(default_path)

    @staticmethod
    def _load_yaml(path):
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def _validate_keys(self, user_dict):
        unknown_keys = set(user_dict) - set(self._default_dict)
        if unknown_keys:
            raise ValueError(f"Unknown config keys: {unknown_keys}")

    def load(self, user_opt=None) -> config:
        if user_opt is None:
            user_dict = {}
        elif isinstance(user_opt, config):
            user_dict = vars(user_opt)
        elif isinstance(user_opt, dict):
            user_dict = user_opt
        else:
            raise TypeError("user_opt must be dict, config(SimpleNamespace) or None")

        self._validate_keys(user_dict)
        merged = {**self._default_dict, **user_dict}
        return config(**merged)


def print_tree(tree, exclude_fields=['text', 'page_index']):
    """Print a tree structure with specified fields excluded"""
    cleaned_tree = remove_fields(tree.copy(), exclude_fields, max_len=40)
    pprint(cleaned_tree, sort_dicts=False, width=100)


def create_node_mapping(tree, include_page_ranges=False, max_page=None):
    """Create a mapping of node_id to node for quick lookup"""
    def get_all_nodes(tree):
        if isinstance(tree, dict):
            return [tree] + [node for child in tree.get('nodes', []) for node in get_all_nodes(child)]
        elif isinstance(tree, list):
            return [node for item in tree for node in get_all_nodes(item)]
        return []
    
    all_nodes = get_all_nodes(tree)
    
    if not include_page_ranges:
        return {node["node_id"]: node for node in all_nodes if node.get("node_id")}
    
    mapping = {}
    for i, node in enumerate(all_nodes):
        if node.get("node_id"):
            # Support both start_index (new) and physical_index (old) field names
            start_page = node.get("start_index") or node.get("physical_index") or node.get("page_index")
            
            if i + 1 < len(all_nodes):
                next_node = all_nodes[i + 1]
                end_page = next_node.get("start_index") or next_node.get("physical_index") or next_node.get("page_index")
            else:
                end_page = max_page
            
            mapping[node["node_id"]] = {
                "node": node,
                "start_index": start_page,
                "end_index": end_page
            }
    
    return mapping


def print_wrapped(text, width=100):
    """Print text with word wrapping"""
    for line in text.splitlines():
        print(textwrap.fill(line, width=width))


def extract_pdf_page_images(pdf_path, output_dir="pdf_images"):
    """Extract images from each page of a PDF document"""
    import fitz  # PyMuPDF
    
    os.makedirs(output_dir, exist_ok=True)
    pdf_document = fitz.open(pdf_path)
    page_images = {}
    total_pages = len(pdf_document)
    
    for page_number in range(len(pdf_document)):
        page = pdf_document.load_page(page_number)
        mat = fitz.Matrix(2.0, 2.0)
        pix = page.get_pixmap(matrix=mat)
        img_data = pix.tobytes("jpeg")
        image_path = os.path.join(output_dir, f"page_{page_number + 1}.jpg")
        with open(image_path, "wb") as image_file:
            image_file.write(img_data)
        page_images[page_number + 1] = image_path
        print(f"Saved page {page_number + 1} image: {image_path}")
    
    pdf_document.close()
    return page_images, total_pages


def get_page_images_for_nodes(node_list, node_map, page_images):
    """Get PDF page images corresponding to the retrieved nodes"""
    image_paths = []
    seen_pages = set()
    
    for node_id in node_list:
        node_info = node_map[node_id]
        for page_num in range(node_info['start_index'], node_info['end_index'] + 1):
            if page_num not in seen_pages and page_num in page_images:
                image_paths.append(page_images[page_num])
                seen_pages.add(page_num)
    
    return image_paths