#!/usr/bin/env python3
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import os
import sys
import shutil
import tempfile
import zipfile
import tarfile
import xml.etree.ElementTree as ET
import base64
import re
import threading
from datetime import datetime
from html import unescape
from urllib.parse import unquote
from collections import defaultdict

def strip_html_tags(text):
    if not text:
        return ''
    text = re.sub(r'<[^>]+>', '', text)
    text = text.strip()
    return text

def fix_encoding(text):
    if not text:
        return text
    try:
        text = text.encode('cp1251', errors='replace').decode('utf-8', errors='replace')
    except:
        pass
    text = text.replace('\uffff', '').replace('\ufffd', '')
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)
    return text

def clean_text(text):
    if not text:
        return ''
    text = unescape(text)
    text = fix_encoding(text)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\s+', ' ', text)
    text = text.strip()
    return text

def parse_moodle_multichoice(text):
    options = []
    rightanswer = ''
    parts = text.split('~')
    for part in parts:
        part = part.strip()
        if not part or 'MULTICHOICE' in part:
            continue
        frac_match = re.match(r'%([-+]?[\d\.]+)%(.*)', part)
        if frac_match:
            try:
                raw_fraction = float(frac_match.group(1))
                answer_text = frac_match.group(2).strip()
                is_correct = raw_fraction > 0
                options.append({
                    'text': answer_text,
                    'clean_text': clean_text(answer_text),
                    'is_correct': is_correct
                })
                if is_correct and not rightanswer:
                    rightanswer = answer_text
            except ValueError:
                continue
    return options, rightanswer

def render_cloze_multichoice(text, user_answer=None, fraction_val=0):
    if not text:
        return text
    pattern = re.compile(r'\{(\d+):MULTICHOICE_V:([^}]+)\}')
    
    is_partially_correct = 0.01 <= fraction_val < 0.99
    
    def replace_match(match):
        options_str = match.group(2)
        opts = []
        option_parts = options_str.split('~')
        for option_part in option_parts:
            if not option_part:
                continue
            option_part = option_part.rstrip('#')
            frac_match = re.match(r'%([-+]?[\d\.]+)%(.*)', option_part)
            if frac_match:
                try:
                    raw_fraction = float(frac_match.group(1))
                    answer_text = frac_match.group(2)
                    is_correct = raw_fraction > 0
                    opts.append((raw_fraction, answer_text, is_correct))
                except:
                    pass
        
        html_parts = ['<div class="cloze-options">']
        for fraction, opt_text, is_correct in opts:
            opt_text = unescape(opt_text)
            is_selected = False
            if user_answer is not None:
                clean_opt = strip_html_tags(opt_text).strip()
                clean_ans = strip_html_tags(str(user_answer)).strip()
                is_selected = clean_opt == clean_ans
            
            if is_selected:
                if is_correct and fraction_val > 0:
                    classes = 'cloze-opt selected-correct'
                elif fraction_val >= 0.99:
                    classes = 'cloze-opt selected-correct'
                else:
                    classes = 'cloze-opt selected-incorrect'
            elif not is_selected and is_correct and is_partially_correct:
                classes = 'cloze-opt not-selected-correct'
            else:
                classes = 'cloze-opt'
            
            html_parts.append(f'<span class="{classes}">{opt_text}</span>')
        html_parts.append('</div>')
        return ''.join(html_parts)
    
    return pattern.sub(replace_match, text)

def render_gapselect(text, groups, user_answers, right_answers=None):
    if not text or not groups:
        return text
    
    def replace_placeholder(match):
        n = int(match.group(1))
        if n in groups:
            group_answers = groups[n]
            
            selected_answer = user_answers.get(n, '') if user_answers else ''
            correct_answer = right_answers.get(n, '') if right_answers else ''
            
            selected_clean = clean_text(selected_answer)
            correct_clean = clean_text(correct_answer)
            
            is_correct = selected_clean == correct_clean if selected_clean and correct_clean else False
            
            if selected_clean:
                status_class = 'correct' if is_correct else 'incorrect'
                status_icon = '✓' if is_correct else '✗'
            else:
                status_class = 'neutral'
                status_icon = '—'
            
            default_option_text = selected_answer if selected_answer else '-- выберите --'
            default_option_class = status_class
            
            select_html = f'<span class="gap-inline-item">'
            select_html += f'<select class="gapselect-dropdown {status_class}">'
            select_html += f'<option value="" class="{default_option_class}">{default_option_text}</option>'
            
            for ans in group_answers:
                ans_clean = clean_text(ans['text']) if isinstance(ans, dict) else clean_text(ans)
                is_selected = ans_clean == selected_clean
                is_correct_opt = ans_clean == correct_clean if correct_clean else False
                selected_attr = ' selected' if is_selected else ''
                if is_selected and is_correct_opt:
                    marker = ' ✓'
                elif is_selected and not is_correct_opt:
                    marker = f' ✗ (верно: {correct_answer})'
                elif is_correct_opt:
                    marker = ' ✓'
                else:
                    marker = ''
                ans_text = ans['text'] if isinstance(ans, dict) else ans
                select_html += f'<option value="{ans_text}"{selected_attr}>{ans_text}{marker}</option>'
            
            select_html += '</select>'
            select_html += f'<span class="gap-status {status_class}">{status_icon}</span>'
            select_html += '</span>'
            
            return select_html
        return match.group(0)
    
    result = re.sub(r'\[\[(\d+)\]\]', replace_placeholder, text)
    
    if user_answers and right_answers and groups:
        all_gaps_html = '<div class="gapselect-all-status">'
        correct_count = 0
        total_count = 0
        placeholder_nums = sorted(groups.keys())
        user_answer_values = list(user_answers.values())
        right_answer_values = list(right_answers.values())
        for idx, n in enumerate(placeholder_nums):
            total_count += 1
            selected_answer = user_answer_values[idx] if idx < len(user_answer_values) else ''
            correct_answer = right_answer_values[idx] if idx < len(right_answer_values) else ''
            selected_clean = clean_text(selected_answer)
            correct_clean = clean_text(correct_answer)
            is_correct = selected_clean == correct_clean if selected_clean and correct_clean else False
            if is_correct:
                correct_count += 1
            status_icon = '✓' if is_correct else ('✗' if selected_clean else '—')
            status_class = 'correct' if is_correct else ('incorrect' if selected_clean else 'neutral')
            all_gaps_html += f'<span class="gap-group-status {status_class}">Пропуск {n}: {status_icon}</span> '
        if total_count > 0:
            all_gaps_html += f'<span class="gap-summary">({correct_count}/{total_count} верно)</span>'
        all_gaps_html += '</div>'
        result += all_gaps_html
    
    return result

def get_image_mime(filename):
    ext = os.path.splitext(filename)[1].lower()
    mime_map = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.gif': 'image/gif', '.svg': 'image/svg+xml', '.webp': 'image/webp'}
    return mime_map.get(ext, 'application/octet-stream')

def load_files_mapping(files_xml_path, files_dir):
    mapping = {}
    if os.path.exists(files_xml_path):
        try:
            tree = ET.parse(files_xml_path)
            root = tree.getroot()
            for f in root.findall('.//file'):
                contenthash = f.findtext('contenthash')
                filename = f.findtext('filename')
                if contenthash and filename:
                    subdir = contenthash[:2] if len(contenthash) >= 2 else ''
                    rel_path = f'files/{subdir}/{contenthash}'
                    mapping[filename] = rel_path
        except:
            pass
    return mapping

def load_images_as_base64(files_dir):
    images = {}
    if not os.path.exists(files_dir):
        return images
    for root, dirs, files in os.walk(files_dir):
        for f in files:
            if f.endswith(('.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp')):
                full_path = os.path.join(root, f)
                rel_path = os.path.relpath(full_path, files_dir)
                try:
                    with open(full_path, 'rb') as img:
                        data = base64.b64encode(img.read()).decode('utf-8')
                    images[rel_path] = data
                except:
                    pass
    return images

def image_to_data_uri(data, mime):
    return f'data:{mime};base64,{data}'

def replace_images_in_text(text, files_mapping, backup_dir):
    if not text or '@@PLUGINFILE@@' not in text:
        return text
    
    result = text
    pattern = re.compile(r'@@PLUGINFILE@@/([^<>"\s]+)')
    matches = pattern.findall(result)
    
    for filename in matches:
        decoded_filename = unquote(filename)
        
        rel_path = files_mapping.get(decoded_filename)
        if not rel_path:
            rel_path = files_mapping.get(filename)
        
        if not rel_path:
            rel_path = decoded_filename
            if not os.path.exists(os.path.join(backup_dir, 'files', rel_path)):
                rel_path = filename
        
        if rel_path.startswith('files/'):
            rel_path = rel_path[6:]
        
        full_path = os.path.join(backup_dir, 'files', rel_path)
        replacement = f'@@PLUGINFILE@@/{filename}'
        
        if os.path.exists(full_path):
            try:
                ext = os.path.splitext(filename)[1].lower()
                image_extensions = ['.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp']
                if ext in image_extensions:
                    mime = get_image_mime(filename)
                    with open(full_path, 'rb') as f:
                        data = base64.b64encode(f.read()).decode('utf-8')
                    replacement = image_to_data_uri(data, mime)
                else:
                    mime_types = {'.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', '.xls': 'application/vnd.ms-excel', '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', '.doc': 'application/msword', '.pdf': 'application/pdf', '.zip': 'application/zip'}
                    mime = mime_types.get(ext, 'application/octet-stream')
                    with open(full_path, 'rb') as f:
                        data = base64.b64encode(f.read()).decode('utf-8')
                    replacement = f'<a href="data:{mime};base64,{data}" download="{filename}">Скачать {filename}</a>'
            except Exception as e:
                pass
        
        full_replace = f'<a href="@@PLUGINFILE@@/{filename}">'
        if full_replace in result:
            result = result.replace(full_replace, replacement, 1)
        else:
            result = result.replace(f'@@PLUGINFILE@@/{filename}', replacement)
    
    result = re.sub(r'@@PLUGINFILE@@/', '', result)
    return result

def clean_cdata(text):
    if not text:
        return text
    text = re.sub(r'<!\[CDATA\[', '', text)
    text = re.sub(r']]>', '', text)
    text = re.sub(r'<!--\[CDATA\[', '', text)
    text = re.sub(r'\]+-->', '', text)
    return text

def parse_questions(xml_path, files_mapping, backup_dir):
    tree = ET.parse(xml_path)
    root = tree.getroot()
    questions = {}
    
    for elem in root.findall('.//question'):
        qid = elem.get('id')
        if not qid:
            continue
        
        qtype = elem.findtext('qtype') or 'unknown'
        name_elem = elem.find('.//name/text')
        name = name_elem.text if name_elem is not None else elem.findtext('.//name') or ''
        name = fix_encoding(name)
        qtext_raw = elem.findtext('questiontext') or ''
        
        qtext = clean_cdata(unescape(qtext_raw))
        qtext = fix_encoding(qtext)
        qtext = replace_images_in_text(qtext, files_mapping, backup_dir)
        
        defaultmark = float(elem.findtext('defaultmark') or '0')
        
        options = []
        rightanswer = ''
        
        if qtype == 'multichoice':
            plugin = elem.find('plugin_qtype_multichoice_question')
            if plugin is not None:
                for ans in plugin.findall('.//answer'):
                    answer_id = ans.get('id', '')
                    fraction = ans.findtext('fraction') or '0'
                    anstext = ans.findtext('answertext') or ''
                    anstext_orig = anstext
                    anstext = clean_cdata(unescape(anstext))
                    anstext_clean = replace_images_in_text(anstext, files_mapping, backup_dir)
                    frac_val = float(fraction)
                    is_correct = frac_val >= 0.5 or frac_val >= 50
                    options.append({'text': anstext_clean, 'clean_text': clean_text(anstext), 'is_correct': is_correct, 'answer_id': answer_id})
                    if is_correct and not rightanswer:
                        rightanswer = anstext_clean
            
            if not options and 'MULTICHOICE' in qtext_raw:
                options, rightanswer = parse_moodle_multichoice(qtext_raw)
        
        elif qtype in ('match', 'ddmatch'):
            sub_q_ids = []
            subanswers = []
            
            plugin = elem.find('plugin_qtype_match_question')
            if plugin is None:
                plugin = elem.find('plugin_qtype_ddmatch_question')
            if plugin is not None:
                for m in plugin.findall('.//match'):
                    q_text = m.findtext('questiontext') or ''
                    q_text = clean_cdata(unescape(q_text))
                    q_text = replace_images_in_text(q_text, files_mapping, backup_dir)
                    a_text = m.findtext('answertext') or ''
                    a_text = clean_cdata(unescape(a_text))
                    a_text = replace_images_in_text(a_text, files_mapping, backup_dir)
                    
                    sub_q_ids.append({'id': m.get('id', ''), 'text': q_text, 'clean_text': clean_text(q_text)})
                    subanswers.append(a_text)
            
            questions[qid] = {'id': qid, 'name': name, 'questiontext': qtext, 'qtype': qtype, 'defaultmark': defaultmark, 'subquestions': sub_q_ids, 'subanswers': subanswers, 'rightanswer': '', 'options': []}
            continue
        
        elif qtype == 'shortanswer':
            plugin = elem.find('plugin_qtype_shortanswer_question')
            if plugin is not None:
                for ans in plugin.findall('.//answer'):
                    fraction = ans.findtext('fraction') or '0'
                    anstext = ans.findtext('answertext') or ''
                    anstext = clean_cdata(unescape(anstext))
                    anstext = replace_images_in_text(anstext, files_mapping, backup_dir)
                    is_correct = float(fraction) >= 0.5
                    options.append({'text': anstext, 'clean_text': clean_text(anstext), 'is_correct': is_correct})
                    if is_correct and not rightanswer:
                        rightanswer = anstext
        
        elif qtype == 'multianswer':
            sub_q_ids = []
            child_sequence = []
            
            for sq in elem.findall('.//subquestion'):
                sq_id = sq.get('id')
                sq_text = sq.findtext('questiontext') or ''
                sq_text = clean_cdata(unescape(sq_text))
                sq_text = replace_images_in_text(sq_text, files_mapping, backup_dir)
                
                sq_answers = []
                for ans in sq.findall('.//answer'):
                    fraction = ans.findtext('fraction') or '0'
                    anstext = ans.findtext('answertext') or ''
                    anstext = clean_cdata(unescape(anstext))
                    anstext = replace_images_in_text(anstext, files_mapping, backup_dir)
                    is_correct = float(fraction) >= 0.5
                    sq_answers.append({'text': anstext, 'clean_text': clean_text(anstext), 'is_correct': is_correct})
                
                sub_q_ids.append({'id': sq_id, 'text': sq_text, 'answers': sq_answers})
            
            plugin = elem.find('.//plugin_qtype_multianswer_question')
            if plugin is not None:
                multianswer = plugin.find('multianswer')
                if multianswer is not None:
                    seq = multianswer.findtext('sequence') or ''
                    if seq:
                        child_sequence = [s.strip() for s in seq.split(',')]
            
            questions[qid] = {'id': qid, 'name': name, 'questiontext': qtext, 'qtype': qtype, 'defaultmark': defaultmark, 'subquestions': sub_q_ids, 'child_sequence': child_sequence, 'rightanswer': '', 'options': []}
            continue
        
        elif qtype == 'gapselect':
            plugin = elem.find('plugin_qtype_gapselect_question')
            answers_by_group = {}
            if plugin is not None:
                for ans in plugin.findall('.//answer'):
                    ans_text = ans.findtext('answertext') or ''
                    ans_text = clean_cdata(unescape(ans_text))
                    ans_text = replace_images_in_text(ans_text, files_mapping, backup_dir)
                    feedback = ans.findtext('feedback') or '1'
                    fraction = ans.findtext('fraction') or '0'
                    is_correct = float(fraction) > 0
                    if feedback not in answers_by_group:
                        answers_by_group[feedback] = []
                    answers_by_group[feedback].append({'text': ans_text, 'clean_text': clean_text(ans_text), 'is_correct': is_correct})
            
            placeholder_order = re.findall(r'\[\[(\d+)\]\]', qtext)
            
            feedback_groups_sorted = sorted(answers_by_group.keys(), key=lambda x: int(x) if x.isdigit() else 0)
            gap_groups = {}
            for idx, placeholder_num in enumerate(placeholder_order):
                if idx < len(feedback_groups_sorted):
                    group_key = feedback_groups_sorted[idx]
                    gap_groups[int(placeholder_num)] = answers_by_group[group_key]
                else:
                    cycle_idx = idx % len(feedback_groups_sorted) if feedback_groups_sorted else 0
                    if feedback_groups_sorted:
                        group_key = feedback_groups_sorted[cycle_idx]
                        gap_groups[int(placeholder_num)] = answers_by_group[group_key]
                    else:
                        gap_groups[int(placeholder_num)] = []
            
            questions[qid] = {'id': qid, 'name': name, 'questiontext': qtext, 'qtype': qtype, 'defaultmark': defaultmark, 'gap_groups': gap_groups, 'placeholder_order': placeholder_order, 'options': [], 'rightanswer': '', 'subquestions': [], 'subanswers': []}
            continue
        
        questions[qid] = {'id': qid, 'name': name, 'questiontext': qtext, 'qtype': qtype, 'defaultmark': defaultmark, 'options': options, 'rightanswer': rightanswer, 'subquestions': [], 'subanswers': []}
    
    return questions

def parse_grades(xml_path):
    if not os.path.exists(xml_path):
        return {}
    tree = ET.parse(xml_path)
    root = tree.getroot()
    grades = {}
    for gg in root.findall('.//grade_grade'):
        uid = gg.findtext('userid')
        fg = gg.findtext('finalgrade')
        if uid and fg and fg != '$@NULL@$':
            try:
                grades[uid] = float(fg)
            except:
                grades[uid] = fg
    return grades

def parse_users(xml_path):
    if not os.path.exists(xml_path):
        return {}
    tree = ET.parse(xml_path)
    root = tree.getroot()
    users = {}
    for user in root.findall('.//user'):
        uid = user.get('id')
        firstname = fix_encoding(user.findtext('firstname') or '')
        lastname = fix_encoding(user.findtext('lastname') or '')
        users[uid] = {'firstname': firstname, 'lastname': lastname}
    return users

def parse_attempts(xml_path):
    tree = ET.parse(xml_path)
    root = tree.getroot()
    attempts = {}
    
    for attempt in root.findall('.//attempt'):
        uid = attempt.findtext('userid')
        if not uid:
            continue
        
        timemod = attempt.findtext('timemodified') or '0'
        qu = attempt.find('./question_usage')
        qattempts = []
        
        if qu is not None:
            for qa in qu.findall('.//question_attempt'):
                slot = qa.findtext('slot') or '0'
                qid = qa.findtext('questionid') or '0'
                responsesummary = qa.findtext('responsesummary') or ''
                rightanswer = qa.findtext('rightanswer') or ''
                
                fraction = '0.0'
                timing = {'opened': None, 'answered': None, 'submitted': None}
                steps = qa.find('steps')
                if steps is not None:
                    steps_list = list(steps.findall('.//step'))
                    for i, step in enumerate(steps_list):
                        state = step.findtext('state')
                        fr = step.findtext('fraction')
                        tc = step.findtext('timecreated')
                        
                        if state == 'todo' and not timing['opened'] and tc:
                            timing['opened'] = tc
                        elif state == 'complete' and not timing['answered'] and tc:
                            timing['answered'] = tc
                        elif state in ('gradedright', 'gradedwrong') and not timing['submitted'] and tc:
                            timing['submitted'] = tc
                            if fr and fr != '$@NULL@$':
                                fraction = str(float(fr))
                        
                        if state in ('gradedright', 'gradedwrong') and fr and fr != '$@NULL@$':
                            fraction = str(float(fr))
                    
                    if fraction == '0.0':
                        for step in steps_list:
                            fr = step.findtext('fraction')
                            if fr and fr != '$@NULL@$':
                                try:
                                    fraction = str(float(fr))
                                    break
                                except:
                                    pass
                
                user_answer_raw = ''
                user_answer_position = None  # Position in _order for multichoice
                sub_answers = {}
                option_order = []  # _order for multichoice questions
                if steps is not None:
                    for step in steps_list:
                        for resp in step.findall('.//response'):
                            for var in resp.findall('.//variable'):
                                name = var.findtext('name')
                                val = var.findtext('value') or ''
                                if val and val != '$@NULL@$':
                                    if name == 'answer':
                                        user_answer_raw = val
                                        try:
                                            user_answer_position = int(val)
                                        except:
                                            pass
                                    elif name == '_order':
                                        option_order = [v.strip() for v in val.split(',') if v.strip()]
                                    elif name and name.startswith('sub') and name.endswith('_answer'):
                                        sub_answers[name] = val
                        resp_text = step.findtext('responsetext')
                        if resp_text and resp_text != '$@NULL@$':
                            if not user_answer_raw:
                                user_answer_raw = resp_text
                
                
                qattempts.append({'slot': slot, 'questionid': qid, 'responsesummary': responsesummary, 'rightanswer': rightanswer, 'fraction': fraction, 'timing': timing, 'user_answer_raw': user_answer_raw, 'user_answer_position': user_answer_position, 'option_order': option_order, 'sub_answers': sub_answers})
        
        attempts[uid] = {'timemodified': timemod, 'question_attempts': qattempts}
    
    return attempts

def parse_match_pairs(text):
    pairs = []
    if not text:
        return pairs
    parts = re.split(r';\s*', text)
    for part in parts:
        part = part.strip()
        if ' -> ' in part:
            idx = part.index(' -> ')
            q = part[:idx].strip()
            a = part[idx+4:].strip()
            pairs.append((q, a))
    return pairs

def parse_multianswer_parts(text):
    return re.split(r'(?=\{[^}]+\})', text)

def render_multichoice(question, user_answer, rightanswer, fraction_val=0, has_raw_answer=False, responsesummary='', option_order=None, user_answer_position=None):
    options = question.get('options', [])
    user_clean = clean_text(user_answer)
    
    user_answer_text = responsesummary if responsesummary else user_clean
    
    try:
        f_val = float(str(fraction_val).replace(',', '.'))
    except:
        f_val = 0.0
    
    user_selected_idx = None
    
    # Try to use option_order if available
    if option_order and user_answer_position is not None:
        # Build mapping from answer ID to original index in our options list
        answer_id_to_index = {}
        for i, opt in enumerate(options):
            answer_id = opt.get('answer_id', '')
            if answer_id:
                answer_id_to_index[str(answer_id)] = i
        
        # user_answer_position is the position in _order
        if 0 <= user_answer_position < len(option_order):
            selected_answer_id = str(option_order[user_answer_position])
            if selected_answer_id in answer_id_to_index:
                user_selected_idx = answer_id_to_index[selected_answer_id]
    
    # Fallback: if option_order didn't work, try the old method
    if user_selected_idx is None and not responsesummary and user_answer:
        try:
            user_answer_int = int(user_answer)
            
            correct_indices = [i for i, o in enumerate(options) if o.get('is_correct')]
            if not correct_indices:
                user_selected_idx = user_answer_int
            else:
                detected_offset = None
                for correct_idx in correct_indices:
                    potential_offset = correct_idx - user_answer_int
                    if -5 <= potential_offset <= 5:
                        candidate_idx = user_answer_int + potential_offset
                        if 0 <= candidate_idx < len(options):
                            detected_offset = potential_offset
                            break
                
                if detected_offset is None:
                    detected_offset = 0
                
                user_selected_idx = user_answer_int + detected_offset
        except:
            pass
    
    is_correct = f_val >= 0.95
    is_partially_correct = 0.05 <= f_val < 0.95
    
    has_image_options = any('data:image' in str(opt.get('text', '')) or '<img' in str(opt.get('text', '')) for opt in options)
    correct_opts = [o for o in options if o['is_correct']]
    
    def normalize_text(text):
        if not text:
            return ''
        text = re.sub(r'<[^>]+>', '', text)
        text = unescape(text)
        text = text.replace('\xa0', ' ').replace('&nbsp;', ' ')
        text = text.strip().lower()
        return text
    
    html = '<div class="answer-section"><div class="answer-label">Ваш ответ:</div>'
    
    user_norm = normalize_text(user_answer_text) if user_answer_text else ''
    
    if has_image_options:
        html += '<div class="img-options">'
        
        for idx, opt in enumerate(options):
            opt_text = opt.get('text', '')
            is_correct_opt = opt.get('is_correct', False)
            opt_norm = normalize_text(opt_text)
            
            is_selected = False
            if user_selected_idx is not None:
                is_selected = (idx == user_selected_idx)
            elif user_norm and opt_norm:
                is_selected = (user_norm == opt_norm) or (user_norm in opt_norm) or (opt_norm in user_norm)
            
            if is_selected:
                if is_correct_opt and f_val > 0:
                    div_class = 'img-option selected-correct'
                    marker = '✓ Ваш выбор (верно)'
                elif f_val >= 0.99:
                    div_class = 'img-option selected-correct'
                    marker = '✓ Ваш выбор (верно)'
                else:
                    div_class = 'img-option selected-incorrect'
                    marker = '✗ Ваш выбор (неверно)'
            elif is_correct_opt and (is_partially_correct or f_val < 0.05):
                div_class = 'img-option correct-target'
                marker = '(Правильный ответ)'
            else:
                div_class = 'img-option'
                marker = ''
            
            html += f'<div class="{div_class}">{opt_text}<br>{marker}</div>'
        html += '</div>'
    else:
        html += '<div style="margin-top: 10px;"><select class="answer-select '
        html += 'correct' if (user_selected_idx is not None or user_norm) and is_correct else ('incorrect' if (user_selected_idx is not None or user_norm) else 'neutral')
        html += '"><option value="">-- Выберите ответ --</option>'
        
        for idx, opt in enumerate(options):
            opt_text = opt.get('text', '')
            opt_norm = normalize_text(opt_text)
            
            is_user_selected = False
            if user_selected_idx is not None:
                is_user_selected = (idx == user_selected_idx)
            elif user_norm and opt_norm:
                is_user_selected = (user_norm == opt_norm) or (user_norm in opt_norm) or (opt_norm in user_norm)
            
            selected = ' selected' if is_user_selected else ''
            
            if is_user_selected:
                if opt['is_correct'] and f_val > 0:
                    correct_marker = ' ✓'
                    correct_class = 'correct'
                elif f_val >= 0.99:
                    correct_marker = ' ✓'
                    correct_class = 'correct'
                else:
                    correct_marker = ' ✗'
                    correct_class = 'incorrect'
            elif opt['is_correct'] and is_partially_correct:
                correct_marker = ' ✓'
                correct_class = 'correct'
            else:
                correct_marker = ''
                correct_class = ''
            
            user_marker = ' ← Ваш ответ' if is_user_selected else ''
            html += f'<option value="{opt["clean_text"]}"{selected} class="{correct_class}">{opt_text}{correct_marker}{user_marker}</option>'
        
        html += '</select></div>'
    
    html += '</div>'
    
    html += '<div class="answer-section"><div class="answer-label">Правильный ответ:</div>'
    if rightanswer and rightanswer != '$@NULL@$':
        right_answers = [r.strip() for r in rightanswer.split(';') if r.strip()]
        if len(right_answers) == 1:
            html += f'<div class="answer-card correct">{right_answers[0]} ✓</div>'
        else:
            for ra in right_answers:
                html += f'<div class="answer-card correct">{ra} ✓</div>'
    elif correct_opts:
        if len(correct_opts) == 1:
            html += f'<div class="answer-card correct">{correct_opts[0]["text"]} ✓</div>'
        else:
            for opt in correct_opts:
                html += f'<div class="answer-card correct">{opt["text"]} ✓</div>'
    else:
        html += '<div class="answer-card neutral">(не определён)</div>'
    html += '</div>'
    
    return html

def render_match(question, user_answer, rightanswer):
    subquestions = question.get('subquestions', [])
    subanswers = question.get('subanswers', [])
    
    html = '<div class="answer-section"><div class="answer-label">Ваш ответ:</div>'
    html += '<table class="match-table"><thead><tr><th>Вопрос</th><th></th><th>Ваш ответ</th><th>Правильный</th></tr></thead><tbody>'
    
    user_pairs = parse_match_pairs(user_answer)
    correct_count = 0
    
    def normalize(s):
        return ' '.join(s.lower().split()) if s else ''
    
    for i, sq in enumerate(subquestions):
        sq_text = sq['text']
        correct_ans = subanswers[i] if i < len(subanswers) else ''
        user_ans = ''
        
        sq_clean = sq['clean_text']
        sq_norm = normalize(sq_clean)
        for pair in user_pairs:
            pair_norm = normalize(pair[0])
            if pair_norm == sq_norm or sq_norm in pair_norm or pair_norm in sq_norm:
                user_ans = pair[1]
                break
        
        is_correct = user_ans.strip() == correct_ans.strip() if user_ans and correct_ans else False
        if is_correct:
            correct_count += 1
        
        if not user_ans:
            row_class = 'match-row-neutral'
            user_display = '<span class="no-answer">ответ не дан</span>'
        elif is_correct:
            row_class = 'match-row-correct'
            user_display = user_ans
        else:
            row_class = 'match-row-wrong'
            user_display = f'{user_ans} ✗'
        
        html += f'''<tr class="{row_class}">
            <td>{sq_text}</td>
            <td class="match-arrow">&rarr;</td>
            <td>{user_display}</td>
            <td>{correct_ans} {'✓' if is_correct else ''}</td>
        </tr>'''
    
    html += '</tbody></table>'
    
    if not user_pairs:
        html += '<div class="answer-card neutral">Ответ не дан</div>'
    elif correct_count == len(subquestions):
        html += f'<div class="answer-card correct">Все {len(subquestions)} соответствий верны ✓</div>'
    else:
        html += f'<div class="answer-card partial">Верно {correct_count} из {len(subquestions)}</div>'
    
    html += '</div>'
    return html

def render_gapselect_q(question, user_answer, rightanswer, qtext, fraction_val=0):
    gap_groups = question.get('gap_groups', {})
    placeholder_order = question.get('placeholder_order', [])
    
    user_parts = re.findall(r'\{([^}]+)\}', user_answer) if user_answer else []
    right_parts = re.findall(r'\{([^}]+)\}', rightanswer) if rightanswer else []
    
    html = '<div class="answer-section">'
    
    if not user_parts:
        html += '<div class="answer-card neutral">Ответ не дан</div>'
    else:
        correct_count = sum(1 for i, ua in enumerate(user_parts) if i < len(right_parts) and ua == right_parts[i])
        total_count = len(right_parts) if right_parts else len(user_parts)
        if correct_count == total_count:
            html += f'<div class="answer-card correct">Все {total_count} ответов верны ✓</div>'
        else:
            html += f'<div class="answer-card partial">Верно {correct_count} из {total_count}</div>'
    
    html += '</div>'
    
    return html

def render_multianswer(question, user_answer, rightanswer, qtext, all_questions=None, fraction_val=0, sub_answers=None):
    subquestions = question.get('subquestions', [])
    child_sequence = question.get('child_sequence', [])
    
    user_parts = parse_multianswer_parts(user_answer)
    right_parts = parse_multianswer_parts(rightanswer)
    
    if sub_answers is None:
        sub_answers = {}
    
    def get_user_answer_for_idx(idx):
        sub_key = f'sub{idx+1}_answer'
        if sub_key in sub_answers:
            return sub_answers[sub_key]
        if idx < len(user_parts):
            return user_parts[idx]
        return ''
    
    def get_option_text_for_index(child_q, index_str):
        if not child_q or not index_str:
            return ''
        
        try:
            idx = int(index_str)
        except:
            return index_str
        
        child_qtext = child_q.get('questiontext', '')
        pattern = re.compile(r'\{(\d+):MULTICHOICE_V:([^}]+)\}')
        match = pattern.search(child_qtext)
        if match:
            options_str = match.group(2)
            option_parts = options_str.split('~')
            option_list = []
            for option_part in option_parts:
                if not option_part:
                    continue
                option_part = option_part.rstrip('#')
                frac_match = re.match(r'%([-+]?[\d\.]+)%(.*)', option_part)
                if frac_match:
                    answer_text = frac_match.group(2)
                    option_list.append(answer_text)
            
            if 0 <= idx < len(option_list):
                return unescape(option_list[idx])
        
        return index_str
    
    if 'MULTICHOICE_V' in qtext or '{#' in qtext:
        def replace_placeholder(match):
            n = int(match.group(1))
            idx = n - 1
            
            user_ans = get_user_answer_for_idx(idx)
            correct_ans = right_parts[idx] if idx < len(right_parts) else ''
            
            user_answer_text = user_ans
            
            if idx < len(child_sequence) and all_questions:
                child_qid = child_sequence[idx]
                child_q = all_questions.get(child_qid, {})
                
                if 'MULTICHOICE_V' in child_q.get('questiontext', ''):
                    if user_ans and user_ans.isdigit():
                        user_answer_text = get_option_text_for_index(child_q, user_ans)
                    return render_cloze_multichoice(child_q.get('questiontext', ''), user_answer_text if user_answer_text else None, fraction_val)
            
            if not user_ans:
                return '<span class="multianswer-blank">[не дан]</span>'
            
            is_correct = user_ans == correct_ans if user_ans and correct_ans else False
            
            if is_correct:
                return f'<span class="multianswer-correct">{user_ans}</span>'
            else:
                return f'<span class="multianswer-incorrect">{user_ans}</span>'
        
        modified_qtext = re.sub(r'\{#(\d+)\}', replace_placeholder, qtext)
        
        html = '<div class="answer-section"><div class="answer-label">Ваш ответ:</div>'
        html += f'<div class="multianswer-inline">{modified_qtext}</div>'
        
        correct_count = 0
        for i in range(len(child_sequence) if child_sequence else (len(right_parts) if right_parts else 0)):
            if i < len(right_parts):
                if get_user_answer_for_idx(i) == right_parts[i]:
                    correct_count += 1
        total_count = len(child_sequence) if child_sequence else (len(right_parts) if right_parts else 0)
        
        has_any_answer = any(get_user_answer_for_idx(i) for i in range(len(child_sequence) if child_sequence else 1))
        if not has_any_answer:
            html += '<div class="answer-card neutral">Ответ не дан</div>'
        elif correct_count == total_count:
            html += f'<div class="answer-card correct">Все {total_count} ответов верны ✓</div>'
        else:
            html += f'<div class="answer-card partial">Верно {correct_count} из {total_count}</div>'
        
        html += '</div>'
        return html
    
    html = '<div class="answer-section"><div class="answer-label">Ваш ответ:</div>'
    
    if not subquestions:
        html += '<select class="answer-select neutral"><option value="">-- Выберите ответ --</option></select>'
    else:
        html += '<select class="answer-select incorrect"><option value="">-- Выберите ответ --</option>'
        
        for i, sq in enumerate(subquestions):
            sq_text = sq.get('text', '')
            sq_answers = sq.get('answers', [])
            
            user_part = user_parts[i] if i < len(user_parts) else ''
            user_part_clean = clean_text(user_part)
            
            html += f'<optgroup label="Часть {i+1}: {clean_text(sq_text)[:50]}...">'
            
            for ans in sq_answers:
                selected = ' selected' if ans['clean_text'] == user_part_clean else ''
                correct_marker = ' ✓' if ans['is_correct'] else ''
                html += f'<option value="{ans["clean_text"]}"{selected}>{ans["text"]}{correct_marker}</option>'
            
            html += '</optgroup>'
        
        html += '</select>'
    
    html += '</div>'
    return html

def render_shortanswer(question, user_answer, rightanswer):
    options = question.get('options', [])
    correct_opts = [o for o in options if o['is_correct']]
    
    user_clean = clean_text(user_answer).lower() if user_answer else ''
    is_correct = any(user_clean == clean_text(opt['text']).lower() for opt in correct_opts) if user_clean else False
    
    html = '<div class="answer-section"><div class="answer-label">Ваш ответ:</div>'
    if user_answer and user_answer != '$@NULL@$':
        status_class = 'correct' if is_correct else 'incorrect'
        icon = '✓' if is_correct else '✗'
        html += f'<div class="answer-card {status_class}">{user_answer} {icon}</div>'
    else:
        html += '<div class="answer-card neutral">(нет ответа)</div>'
    
    html += '<div class="answer-label">Правильный ответ:</div>'
    if rightanswer and rightanswer != '$@NULL@$':
        html += f'<div class="answer-card correct">{rightanswer} ✓</div>'
    elif correct_opts:
        html += f'<div class="answer-card correct">{correct_opts[0]["text"]} ✓</div>'
    else:
        html += '<div class="answer-card neutral">(не определён)</div>'
    html += '</div>'
    
    return html

def render_generic(user_answer, rightanswer):
    html = '<div class="answer-section"><div class="answer-label">Ваш ответ:</div>'
    if user_answer and user_answer != '$@NULL@$':
        html += f'<div class="answer-card">{user_answer}</div>'
    else:
        html += '<div class="answer-card neutral">(нет ответа)</div>'
    
    html += '<div class="answer-label">Правильный ответ:</div>'
    if rightanswer and rightanswer != '$@NULL@$':
        html += f'<div class="answer-card correct">{rightanswer} ✓</div>'
    else:
        html += '<div class="answer-card neutral">(не определён)</div>'
    html += '</div>'
    
    return html

def generate_html_report(users, grades, questions, attempts, backup_name, output_path, files_dir, show_correct_attempts=True):
    images = load_images_as_base64(files_dir)
    
    html = '''<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<title>''' + backup_name + '''</title>
<script src="https://polyfill.io/v3/polyfill.min.js?features=es6"></script>
<script id="MathJax-script" async src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>
<style>
body { font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }
.student { background: #fff; margin: 30px auto; padding: 20px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,.1); max-width: 1000px; }
.student-header { margin-bottom: 15px; }
.student-name { font-size: 1.4em; color: #2c3e50; }
.student-info { color: #7f8c8d; font-size: .9em; }
.question-block { margin: 15px 0; padding: 12px 15px; border-radius: 6px; border-left: 4px solid #ccc; background: #fff; }
.question-block.correct { border-left-color: #4caf50; }
.question-block.incorrect { border-left-color: #f44336; }
.question-block.partial { border-left-color: #ff9800; }
.q-header { font-weight: bold; color: #2c3e50; margin-bottom: 10px; }
.q-text { margin: 10px 0; line-height: 1.6; }
.q-text img { max-width: 100%; height: auto; }
.answer-section { margin: 15px 0; padding: 10px; background: #fafafa; border-radius: 4px; }
.answer-label { font-weight: bold; margin-bottom: 5px; color: #555; font-size: 0.9em; }
.answer-card { padding: 8px 12px; border-radius: 4px; margin: 5px 0; }
.answer-card.correct { background: #e8f5e9; border-left: 3px solid #4caf50; }
.answer-card.incorrect { background: #ffebee; border-left: 3px solid #f44336; }
.answer-card.partial { background: #fff3e0; border-left: 3px solid #ff9800; }
.answer-card.neutral { background: #f5f5f5; border-left: 3px solid #9e9e9e; }
select.answer-select { padding: 6px 10px; border-radius: 4px; border: 2px solid #ddd; font-size: 14px; background: #fff; min-width: 200px; }
select.answer-select.correct { border-color: #4caf50; background: #e8f5e9; }
select.answer-select.incorrect { border-color: #f44336; background: #ffebee; }
.img-options { display: flex; flex-wrap: wrap; gap: 10px; justify-content: center; margin: 15px 0; }
.img-option { flex: 1 1 200px; max-width: 250px; border: 2px solid #ddd; border-radius: 8px; padding: 8px; text-align: center; }
.img-option.selected-correct { border: 3px solid #28a745; background: #f8fff9; box-shadow: 0 0 10px rgba(40, 167, 69, 0.2); }
.img-option.selected-incorrect { border: 3px solid #dc3545; background: #fff8f8; }
.img-option.correct-target { border: 2px dashed #28a745; opacity: 0.8; background: #fafffa; }
.img-option img { max-width: 100%; height: auto; }
.status-icon { font-weight: bold; margin-right: 5px; }
.timing-table { width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 0.85em; }
.timing-table th, .timing-table td { border: 1px solid #ddd; padding: 6px; text-align: left; }
.timing-table th { background: #f0f0f0; }
.match-table { width: 100%; border-collapse: collapse; margin: 10px 0; }
.match-table th, .match-table td { border: 1px solid #ddd; padding: 8px; }
.match-table th { background: #f0f0f0; }
.match-row-correct { background: #e8f5e9; }
.match-row-wrong { background: #ffebee; }
.match-row-neutral { background: #f5f5f5; color: #888; }
.cloze-options { display: flex; flex-wrap: wrap; gap: 8px; margin: 10px 0; }
.cloze-opt { padding: 6px 12px; border-radius: 4px; background: #f0f0f0; border: 1px solid #ddd; }
.cloze-opt.selected-correct { background: #e8f5e9; border-color: #4caf50; }
.cloze-opt.selected-incorrect { background: #ffebee; border-color: #f44336; }
.cloze-opt.not-selected-correct { background: #fff3e0; border-color: #ff9800; }
</style>
</head>
<body>'''
    
    for uid, user_info in users.items():
        if uid not in attempts:
            continue
        
        attempt = attempts[uid]
        qattempts = attempt.get('question_attempts', [])
        if not qattempts:
            continue
        
        firstname = user_info.get('firstname', '')
        lastname = user_info.get('lastname', '')
        fullname = f'{firstname} {lastname}'.strip() or f'Пользователь {uid}'
        grade = grades.get(uid)
        grade_str = f'{grade:.2f}' if isinstance(grade, float) else str(grade) if grade else 'Нет данных'
        
        try:
            date_str = datetime.fromtimestamp(int(attempt['timemodified'])).strftime('%Y-%m-%d %H:%M:%S')
        except:
            date_str = 'неизвестно'
        
        html += f'''<div class="student">
<div class="student-header"><div class="student-name">Студент: {fullname} (ID: {uid})</div>
<div class="student-info">Балл: {grade_str} | Дата: {date_str}</div></div>'''
        
        sorted_qas = sorted(qattempts, key=lambda x: int(x['slot']))
        
        for qa in sorted_qas:
            try:
                fraction_val = float(str(qa.get('fraction', '0')).replace(',', '.'))
            except:
                fraction_val = 0.0
            
            if not show_correct_attempts and fraction_val >= 0.99:
                continue
            
            slot = qa['slot']
            qid = qa['questionid']
            user_answer_raw = qa.get('user_answer_raw', '')
            responsesummary = qa.get('responsesummary', '')
            user_answer = responsesummary if responsesummary else user_answer_raw
            rightanswer = qa.get('rightanswer', '')
            fraction = qa.get('fraction', '0')
            sub_answers = qa.get('sub_answers', {})
            try:
                fraction_val = float(str(fraction).replace(',', '.'))
            except:
                fraction_val = 0.0
            timing = qa.get('timing', {})
            
            question = questions.get(qid)
            if not question:
                continue
            
            qtext = question.get('questiontext', '')
            qtype = question.get('qtype', 'unknown')
            defaultmark = question.get('defaultmark', 0)
            
            fraction_val = float(fraction) if fraction else 0
            
            if 'MULTICHOICE_V' in qtext:
                qtext = render_cloze_multichoice(qtext, user_answer, fraction_val)
            elif qtype == 'gapselect':
                gap_groups = question.get('gap_groups', {})
                placeholder_order = question.get('placeholder_order', [])
                user_parts = re.findall(r'\{([^}]+)\}', user_answer) if user_answer else []
                right_parts = re.findall(r'\{([^}]+)\}', rightanswer) if rightanswer else []
                placeholder_order_nums = [int(p) for p in placeholder_order]
                user_answers_dict = {placeholder_order_nums[i]: user_parts[i] if i < len(user_parts) else '' for i in range(len(placeholder_order_nums))}
                right_answers_dict = {placeholder_order_nums[i]: right_parts[i] if i < len(right_parts) else '' for i in range(len(placeholder_order_nums))}
                qtext = render_gapselect(qtext, gap_groups, user_answers_dict, right_answers_dict)
            
            try:
                points = float(fraction) * defaultmark
            except:
                points = 0.0
            
            fraction_val = float(fraction) if fraction else 0
            if fraction_val >= 0.99:
                status_class = 'correct'
                status_text = 'Верно'
            elif fraction_val >= 0.01:
                status_class = 'partial'
                status_text = 'Частично'
            else:
                status_class = 'incorrect'
                status_text = 'Неверно'
            
            has_cloze = 'cloze-options' in qtext
            
            if has_cloze:
                html += f'<div class="question-block {status_class}"><div class="q-header">Вопрос {slot} — Балл: {points:.2f} / {defaultmark:.1f} ({status_text})</div>'
                html += '<div class="answer-section"><div class="answer-label">Ваш ответ:</div>'
                if fraction_val >= 0.99:
                    html += '<div class="answer-card correct">Выбран правильный вариант ✓</div>'
                elif fraction_val >= 0.01:
                    html += '<div class="answer-card partial">Частично верно</div>'
                else:
                    html += '<div class="answer-card incorrect">Неверный ответ ✗</div>'
                html += '</div></div>'
            elif qtype == 'multianswer':
                html += f'<div class="question-block {status_class}"><div class="q-header">Вопрос {slot} — Балл: {points:.2f} / {defaultmark:.1f} ({status_text})</div>'
                html += render_multianswer(question, user_answer, rightanswer, qtext, questions, fraction_val, sub_answers)
                html += '</div>'
            else:
                html += f'<div class="question-block {status_class}"><div class="q-header">Вопрос {slot} — Балл: {points:.2f} / {defaultmark:.1f} ({status_text})</div>'
                html += f'<div class="q-text math">{qtext}</div>'
                
                if qtype == 'multichoice':
                    has_raw_answer = bool(user_answer_raw) and user_answer_raw != '$@NULL@$'
                    option_order = qa.get('option_order', [])
                    user_answer_position = qa.get('user_answer_position')
                    html += render_multichoice(question, user_answer, rightanswer, fraction_val, has_raw_answer, responsesummary, option_order, user_answer_position)
                elif qtype in ('match', 'ddmatch'):
                    html += render_match(question, user_answer, rightanswer)
                elif qtype == 'gapselect':
                    html += render_gapselect_q(question, user_answer, rightanswer, qtext, fraction_val)
                elif qtype == 'shortanswer':
                    html += render_shortanswer(question, user_answer, rightanswer)
                else:
                    html += render_generic(user_answer, rightanswer)
                
                if timing:
                    html += '<div class="timing-table"><table><thead><tr><th>Шаг</th><th>Время</th><th>Действие</th><th>Состояние</th><th>Баллы</th></tr></thead><tbody>'
                    
                    step_num = 1
                    
                    if timing.get('opened'):
                        try:
                            opened_time = datetime.fromtimestamp(int(timing['opened'])).strftime('%d/%m/%y, %H:%M')
                            html += f'<tr><td>{step_num}</td><td>{opened_time}</td><td>Начало</td><td>Пока нет ответа</td><td>—</td></tr>'
                            step_num += 1
                        except:
                            pass
                    
                    if timing.get('answered'):
                        try:
                            answered_time = datetime.fromtimestamp(int(timing['answered'])).strftime('%d/%m/%y, %H:%M')
                            response_preview = user_answer[:30] + '...' if user_answer and len(user_answer) > 30 else (user_answer or '—')
                            html += f'<tr><td>{step_num}</td><td>{answered_time}</td><td>Сохранено: {response_preview}</td><td>Ответ сохранён</td><td>—</td></tr>'
                            step_num += 1
                        except:
                            pass
                    
                    if timing.get('submitted'):
                        try:
                            submitted_time = datetime.fromtimestamp(int(timing['submitted'])).strftime('%d/%m/%y, %H:%M')
                            if fraction_val >= 0.99:
                                state_html = '<span style="color:green">Верно</span>'
                            elif fraction_val >= 0.01:
                                state_html = '<span style="color:orange">Частично</span>'
                            else:
                                state_html = '<span style="color:red">Неверно</span>'
                            html += f'<tr><td>{step_num}</td><td>{submitted_time}</td><td>Попытка завершена</td><td>{state_html}</td><td>{points:.2f}</td></tr>'
                        except:
                            pass
                    
                    html += '</tbody></table></div>'
                
                html += '</div>'
        
        html += '</div>'
    
    html += '</body></html>'
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)
    
    return html

class MoodleReportGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Moodle Отчёты - Генератор")
        self.root.geometry("600x380")
        self.root.resizable(False, False)
        
        self.mbz_file = ""
        self.output_dir = ""
        
        main_frame = ttk.Frame(root, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        title_label = ttk.Label(main_frame, text="С помощью данной программы можно выгрузить из архива Moodle попытки пользователей в html", font=("Arial", 10), wraplength=550, justify=tk.CENTER)
        title_label.pack(pady=(0, 20))
        
        ttk.Label(main_frame, text="Выберите архив (.mbz):").pack(anchor=tk.W, pady=(10, 5))
        mbz_frame = ttk.Frame(main_frame)
        mbz_frame.pack(fill=tk.X, pady=(0, 10))
        self.mbz_entry = ttk.Entry(mbz_frame)
        self.mbz_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        self.mbz_btn = ttk.Button(mbz_frame, text="Открыть", command=self.select_mbz)
        self.mbz_btn.pack(side=tk.RIGHT)
        
        ttk.Label(main_frame, text="Выберите папку для сохранения:").pack(anchor=tk.W, pady=(10, 5))
        output_frame = ttk.Frame(main_frame)
        output_frame.pack(fill=tk.X, pady=(0, 10))
        self.output_entry = ttk.Entry(output_frame)
        self.output_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        self.output_btn = ttk.Button(output_frame, text="Выбрать", command=self.select_output)
        self.output_btn.pack(side=tk.RIGHT)
        
        self.progress_label = ttk.Label(main_frame, text="")
        self.progress_label.pack(pady=(10, 5))
        self.progress = ttk.Progressbar(main_frame, mode='determinate', length=560)
        self.progress.pack(pady=(0, 15))
        
        self.export_btn = ttk.Button(main_frame, text="Выгрузить", command=self.start_export, state=tk.DISABLED)
        self.export_btn.pack(pady=(10, 0))
        
        self.show_correct_attempts = tk.BooleanVar(value=True)
        self.correct_attempts_check = ttk.Checkbutton(main_frame, text="Отображать правильные попытки", variable=self.show_correct_attempts)
        self.correct_attempts_check.pack(pady=(5, 0))
    
    def select_mbz(self):
        filename = filedialog.askopenfilename(title="Выберите архив Moodle", filetypes=[("Moodle backup", "*.mbz"), ("All files", "*.*")])
        if filename:
            self.mbz_file = filename
            self.mbz_entry.delete(0, tk.END)
            self.mbz_entry.insert(0, filename)
            self.check_ready()
    
    def select_output(self):
        dirname = filedialog.askdirectory(title="Выберите папку")
        if dirname:
            self.output_dir = dirname
            self.output_entry.delete(0, tk.END)
            self.output_entry.insert(0, dirname)
            self.check_ready()
    
    def check_ready(self):
        self.export_btn.config(state=tk.NORMAL if self.mbz_file and self.output_dir else tk.DISABLED)
    
    def start_export(self):
        if not self.mbz_file or not self.output_dir:
            messagebox.showwarning("Внимание", "Выберите архив и папку!")
            return
        self.export_btn.config(state=tk.DISABLED)
        self.mbz_btn.config(state=tk.DISABLED)
        self.output_btn.config(state=tk.DISABLED)
        threading.Thread(target=self.run_export).start()
    
    def run_export(self):
        try:
            self.update_progress(10, "Распаковка...")
            temp_dir = tempfile.mkdtemp()
            extract_dir = os.path.join(temp_dir, "extracted")
            os.makedirs(extract_dir)
            
            try:
                with zipfile.ZipFile(self.mbz_file, 'r') as zip_ref:
                    zip_ref.extractall(extract_dir)
            except:
                with tarfile.open(self.mbz_file, 'r:gz') as tar:
                    tar.extractall(extract_dir)
            
            self.update_progress(30, "Поиск файлов...")
            backup_dir = None
            for root_dir, dirs, files in os.walk(extract_dir):
                if 'questions.xml' in files:
                    backup_dir = root_dir
                    break
            
            if not backup_dir:
                self.show_error("Не найден questions.xml!")
                return
            
            self.update_progress(50, "Обработка данных...")
            users_path = os.path.join(backup_dir, 'users.xml')
            users = parse_users(users_path)
            
            grades_path = None
            quiz_path = None
            for root_dir, dirs, files in os.walk(backup_dir):
                for f in files:
                    if f == 'grades.xml' and 'activities' in root_dir:
                        grades_path = os.path.join(root_dir, f)
                    if f == 'quiz.xml' and 'activities' in root_dir:
                        quiz_path = os.path.join(root_dir, f)
            
            grades = parse_grades(grades_path) if grades_path else {}
            files_xml_path = os.path.join(backup_dir, 'files.xml')
            files_mapping = load_files_mapping(files_xml_path, backup_dir)
            questions = parse_questions(os.path.join(backup_dir, 'questions.xml'), files_mapping, backup_dir)
            attempts = parse_attempts(quiz_path) if quiz_path else {}
            
            self.update_progress(70, "Создание отчётов...")
            backup_name = os.path.splitext(os.path.basename(self.mbz_file))[0]
            output_folder = os.path.join(self.output_dir, backup_name)
            os.makedirs(output_folder, exist_ok=True)
            
            count = 0
            for uid, user_info in users.items():
                if uid not in attempts:
                    continue
                attempt = attempts[uid]
                qattempts = attempt.get('question_attempts', [])
                if not qattempts:
                    continue
                firstname = user_info.get('firstname', '')
                lastname = user_info.get('lastname', '')
                fullname = f'{lastname} {firstname}'.strip() or f'Пользователь_{uid}'
                fullname_safe = fullname.replace(' ', '_').replace('/', '_')
                
                user_html = generate_html_report({uid: user_info}, {uid: grades.get(uid)}, questions, {uid: attempt}, backup_name, os.path.join(output_folder, f'{fullname_safe}_{backup_name}.html'), os.path.join(backup_dir, 'files'), self.show_correct_attempts.get())
                count += 1
            
            self.update_progress(100, "Готово!")
            self.root.after(0, lambda: messagebox.showinfo("Успех", f"Создано {count} отчётов в папке:\n{output_folder}"))
        except Exception as e:
            import traceback
            self.show_error(f"Ошибка: {str(e)}\n{traceback.format_exc()}")
        finally:
            self.root.after(0, self.reset_ui)
            if 'temp_dir' in locals():
                try:
                    shutil.rmtree(temp_dir)
                except:
                    pass
    
    def update_progress(self, value, text):
        self.root.after(0, lambda: self.progress.config(value=value))
        self.root.after(0, lambda: self.progress_label.config(text=text))
    
    def show_error(self, text):
        self.root.after(0, lambda: messagebox.showerror("Ошибка", text))
    
    def reset_ui(self):
        self.progress.config(value=0)
        self.progress_label.config(text="")
        self.export_btn.config(state=tk.NORMAL)
        self.mbz_btn.config(state=tk.NORMAL)
        self.output_btn.config(state=tk.NORMAL)
        self.check_ready()

def main():
    root = tk.Tk()
    app = MoodleReportGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()
