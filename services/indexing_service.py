#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Indexing service for PDF processing
"""

import os
import json
import asyncio
import logging
from typing import Optional

from models.document import Document, DocumentStore, document_store
from config import config_manager
from pageindex import page_index_main, set_api_config, ConfigLoader
from types import SimpleNamespace as pageindex_config

logger = logging.getLogger(__name__)


class IndexingService:
    """Service for indexing PDF documents"""
    
    def __init__(self, store: DocumentStore):
        self.store = store
    
    async def index_document(self, doc_id: str, file_path: str, filename: str, progress_callback=None) -> bool:
        """
        Index a PDF or Markdown document using PageIndex
        
        Args:
            doc_id: Document ID
            file_path: Path to the document file
            filename: Original filename (used for result directory name)
            progress_callback: Optional callback for progress updates
        """
        try:
            # Update status
            self.store.update_document(doc_id, status='indexing')
            
            # Get model configuration
            model_config = config_manager.get_model_config('text')
            model_name = model_config.get('name', 'gpt-4o-mini')
            api_key = model_config.get('api_key', '')
            base_url = model_config.get('base_url', 'https://api.openai.com/v1')
            
            # Set API configuration for PageIndex
            if api_key:
                set_api_config(api_key, base_url)
            
            logger.info(f"Using model: {model_name}, base_url: {base_url}")
            
            # Create PageIndex options
            loader = ConfigLoader()
            opt = loader.load({
                'model': model_name,
                'toc_check_page_num': 20,
                'max_page_num_each_node': 10,
                'max_token_num_each_node': 20000,
                'if_add_node_id': 'yes',
                'if_add_node_summary': 'yes',
                'if_add_doc_description': 'no',
                'if_add_node_text': 'yes'
            })
            
            # Run indexing
            logger.info(f"Starting indexing for {file_path}")
            
            # Run in thread pool to avoid blocking
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: page_index_main(file_path, opt, doc_id=doc_id, progress_callback=progress_callback)
            )
            
            # Get document to find result directory
            doc = self.store.get_document(doc_id)
            if not doc:
                raise ValueError(f"Document {doc_id} not found")
            
            # Save result to document's structure path
            os.makedirs(doc.result_dir, exist_ok=True)
            
            with open(doc.structure_path, 'w', encoding='utf-8') as f:
                json.dump(result, f, indent=2, ensure_ascii=False)
            
            # Extract page images for PDF, or generate for Markdown
            images_dir = os.path.join(doc.result_dir, "images")
            os.makedirs(images_dir, exist_ok=True)
            
            if file_path.lower().endswith(".pdf"):
                from pageindex.utils import extract_pdf_page_images
                try:
                    extract_pdf_page_images(file_path, images_dir)
                except Exception as e:
                    logger.warning(f"Failed to extract PDF images: {e}")
            elif file_path.lower().endswith(".md"):
                from pageindex.utils import generate_text_image
                try:
                    # page_index_main result structure should contain page content or we can re-parse
                    # Actually, we have the result from page_index_main which is the tree structure
                    # But the "pages" are in the document text nodes
                    def extract_pages_from_tree(node, pages_dict):
                        if isinstance(node, dict):
                            start = node.get('start_index')
                            if start and node.get('text'):
                                # Simplified: Use the text of nodes to generate page previews
                                # Since MD pages are virtual, we can just use node text
                                pages_dict[start] = node['text']
                            for child in node.get('nodes', []):
                                extract_pages_from_tree(child, pages_dict)
                        elif isinstance(node, list):
                            for item in node:
                                extract_pages_from_tree(item, pages_dict)
                                
                    pages = {}
                    extract_pages_from_tree(result.get('structure', []), pages)
                    
                    # Also we can just re-read the file to get the original chunks
                    from pageindex.utils import get_page_tokens
                    # Re-run with no logger just to get chunks
                    chunks = get_page_tokens(file_path, model=model_name)
                    
                    for i, (text, _) in enumerate(chunks):
                        page_num = i + 1
                        img_path = os.path.join(images_dir, f"page_{page_num}.jpg")
                        generate_text_image(text, img_path, title=f"Markdown Page {page_num}")
                except Exception as e:
                    logger.warning(f"Failed to generate MD images: {e}")

            # Update document status
            self.store.update_document(doc_id, status='indexed')
            
            logger.info(f"Indexing completed for {filename}, saved to {doc.structure_path}")
            return True
            
        except Exception as e:
            logger.error(f"Indexing error: {e}")
            self.store.update_document(doc_id, status='error', error_message=str(e))
            return False
    
    def get_indexing_status(self, doc_id: str) -> Optional[str]:
        """Get indexing status for a document"""
        doc = self.store.get_document(doc_id)
        if doc:
            return doc.status
        return None


# Create singleton instance
indexing_service = IndexingService(document_store)
