import asyncio
import json
import re
import os
from .utils import (
    count_tokens, 
    generate_node_summary, 
    structure_to_list, 
    write_node_id, 
    format_structure, 
    create_clean_structure_for_description, 
    generate_doc_description,
    print_json,
    print_toc
)

async def get_node_summary(node, summary_token_threshold=200, model=None, max_context=3000):
    node_text = node.get('text', '')
    num_tokens = count_tokens(node_text, model=model)
    
    if num_tokens < summary_token_threshold:
        return node_text
    
    # Safety check for Ollama context limits (truncating if too long)
    if num_tokens > max_context:
        # Truncate text to fit into model context window
        # We keep the beginning and end as they usually contain most info
        head_len = int(max_context * 0.7)
        tail_len = int(max_context * 0.2)
        # Simple character-based truncation as fallback if we don't want to re-count tokens too much
        # But here we just slice the string roughly
        node_text = node_text[:head_len*4] + "\n...[内容过长已截断]...\n" + node_text[-tail_len*4:]
        node['text'] = node_text # Update node text for the API call
        
    return await generate_node_summary(node, model=model)

async def generate_summaries_for_structure_md(structure, summary_token_threshold, model=None, logger=None):
    nodes = structure_to_list(structure)
    total_nodes = len(nodes)
    
    if logger:
        logger.progress(None, None, "生成摘要", detail=f"准备为 {total_nodes} 个节点生成摘要...")
        
    tasks = []
    for node in nodes:
        tasks.append(get_node_summary(node, summary_token_threshold=summary_token_threshold, model=model))
    
    summaries = await asyncio.gather(*tasks)
    
    for node, summary in zip(nodes, summaries):
        if not node.get('nodes'):
            node['summary'] = summary
        else:
            node['prefix_summary'] = summary
            
    if logger:
        logger.progress(None, None, "生成摘要", detail="摘要生成完成")
    return structure

def extract_nodes_from_markdown(markdown_content):
    header_pattern = r'^(#{1,6})\s+(.+)$'
    code_block_pattern = r'^```'
    node_list = []
    
    lines = markdown_content.split('\n')
    in_code_block = False
    
    for line_num, line in enumerate(lines, 1):
        stripped_line = line.strip()
        if re.match(code_block_pattern, stripped_line):
            in_code_block = not in_code_block
            continue
        if not stripped_line:
            continue
        if not in_code_block:
            match = re.match(header_pattern, stripped_line)
            if match:
                title = match.group(2).strip()
                node_list.append({'node_title': title, 'line_num': line_num})
    return node_list, lines

def extract_node_text_content(node_list, markdown_lines):    
    all_nodes = []
    for node in node_list:
        line_content = markdown_lines[node['line_num'] - 1]
        header_match = re.match(r'^(#{1,6})', line_content)
        if header_match is None:
            continue
        processed_node = {
            'title': node['node_title'],
            'line_num': node['line_num'],
            'level': len(header_match.group(1))
        }
        all_nodes.append(processed_node)
    
    for i, node in enumerate(all_nodes):
        start_line = node['line_num'] - 1 
        if i + 1 < len(all_nodes):
            end_line = all_nodes[i + 1]['line_num'] - 1 
        else:
            end_line = len(markdown_lines)
        node['text'] = '\n'.join(markdown_lines[start_line:end_line]).strip()    
    return all_nodes

def update_node_list_with_text_token_count(node_list, model=None):
    result_list = node_list.copy()
    for i in range(len(result_list) - 1, -1, -1):
        current_node = result_list[i]
        current_level = current_node['level']
        
        # Calculate tokens for this node and its potential descendants
        total_text = current_node.get('text', '')
        for j in range(i + 1, len(result_list)):
            if result_list[j]['level'] <= current_level:
                break
            total_text += '\n' + result_list[j].get('text', '')
        
        result_list[i]['text_token_count'] = count_tokens(total_text, model=model)
    return result_list

def tree_thinning_for_index(node_list, min_node_token=None, model=None):
    if min_node_token is None: return node_list
    result_list = node_list.copy()
    nodes_to_remove = set()
    
    for i in range(len(result_list) - 1, -1, -1):
        if i in nodes_to_remove: continue
        current_node = result_list[i]
        if current_node.get('text_token_count', 0) < min_node_token:
            # Merge descendants into this node and mark them for removal
            level = current_node['level']
            descendant_texts = []
            for j in range(i + 1, len(result_list)):
                if result_list[j]['level'] <= level: break
                if j not in nodes_to_remove:
                    descendant_texts.append(result_list[j].get('text', ''))
                    nodes_to_remove.add(j)
            if descendant_texts:
                current_node['text'] = current_node.get('text', '') + '\n\n' + '\n\n'.join(descendant_texts)
                current_node['text_token_count'] = count_tokens(current_node['text'], model=model)
    
    return [node for idx, node in enumerate(result_list) if idx not in nodes_to_remove]

def build_tree_from_nodes(node_list):
    if not node_list: return []
    stack = []
    root_nodes = []
    for node in node_list:
        tree_node = {
            'title': node['title'],
            'text': node['text'],
            'line_num': node['line_num'],
            'nodes': []
        }
        while stack and stack[-1][1] >= node['level']:
            stack.pop()
        if not stack:
            root_nodes.append(tree_node)
        else:
            stack[-1][0]['nodes'].append(tree_node)
        stack.append((tree_node, node['level']))
    return root_nodes

async def md_to_tree(md_path, if_thinning=True, min_token_threshold=1500, if_add_node_summary='no', summary_token_threshold=200, model=None, if_add_doc_description='no', if_add_node_text='no', if_add_node_id='yes', logger=None):
    with open(md_path, 'r', encoding='utf-8') as f:
        markdown_content = f.read()
    
    if logger: logger.progress(10, 100, "Markdown解析", detail="正在提取文档节点...")
    node_list, markdown_lines = extract_nodes_from_markdown(markdown_content)
    nodes_with_content = extract_node_text_content(node_list, markdown_lines)
    
    if if_thinning:
        if logger: logger.progress(30, 100, "Markdown解析", detail="正在执行节点合并优化...")
        nodes_with_content = update_node_list_with_text_token_count(nodes_with_content, model=model)
        nodes_with_content = tree_thinning_for_index(nodes_with_content, min_token_threshold, model=model)
    
    if logger: logger.progress(60, 100, "Markdown解析", detail="正在构建树结构...")
    tree_structure = build_tree_from_nodes(nodes_with_content)

    if if_add_node_id == 'yes':
        write_node_id(tree_structure)

    if if_add_node_summary == 'yes':
        if logger: logger.progress(80, 100, "Markdown解析", detail="正在生成节点摘要...")
        tree_structure = await generate_summaries_for_structure_md(tree_structure, summary_token_threshold=summary_token_threshold, model=model, logger=logger)
        if if_add_node_text == 'no':
            tree_structure = format_structure(tree_structure, order = ['title', 'node_id', 'summary', 'prefix_summary', 'line_num', 'nodes'])
        else:
            tree_structure = format_structure(tree_structure, order = ['title', 'node_id', 'summary', 'prefix_summary', 'text', 'line_num', 'nodes'])
    else:
        order = ['title', 'node_id', 'text', 'line_num', 'nodes'] if if_add_node_text == 'yes' else ['title', 'node_id', 'line_num', 'nodes']
        tree_structure = format_structure(tree_structure, order=order)
    
    result = {'doc_name': os.path.splitext(os.path.basename(md_path))[0], 'structure': tree_structure}
    if if_add_doc_description == 'yes':
        clean_struct = create_clean_structure_for_description(tree_structure)
        result['doc_description'] = generate_doc_description(clean_struct, model=model)
    
    if logger: logger.progress(100, 100, "Markdown解析", detail="完成")
    return result
