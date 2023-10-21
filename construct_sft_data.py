import re

import json

import os
from config.config import *
import pandas as pd

def get_gold_ans(gold_annotaion_path):
    gold_ann = pd.read_excel(gold_annotaion_path)
    num_lines = len(gold_ann)
    vid_2_stem_ans = dict()
    for i in range(num_lines):
        data_dict = dict(gold_ann.loc[i])
        vid = data_dict["就诊流水号"]
        vid = str(vid)
        stem = data_dict["填报数据项编码"]
        ans = data_dict["选项或数据值"]
        if vid not in vid_2_stem_ans:
            vid_2_stem_ans[vid] = dict()
        vid_2_stem_ans[vid][stem] = ans
        # print(ans)
    return vid_2_stem_ans

def count_iterable(i): return sum(1 for _ in i)

def convert_choice_to_phrase(choice, prompt):
    mapping_rule = "(?P<a>A\.)|(?P<b>B\.)|(?P<c>C\.)|(?P<d>D\.)|(?P<UTD>E\.)"
    for line in prompt.split('\n'):
        res = re.finditer(mapping_rule, line)
        for x in res:
            for group_name, group_value in x.groupdict().items():
                if group_value and group_name == choice:
                    return line
    return None

def get_sample_4_sft(file_re_info, rule_info, context_4_stem_vid, gold_ans):
    """
    根据对现有27-48中的stem的规则发现，只有三个关于”禁忌症“的字段需要模型进行问答，以此作为特征构建prompt。
    :param file_re_info: 文件名信息，即一级索引
    :param sec_index_re: 表索引信息，即二级信息
    :param stem_cn_name: stem中文名
    :param rule_info: prompt
    :param context_4_stem_vid: 该就诊中关于该stem的相关病历文本信息
    :return:
    """
    rule_info = rule_info.replace("\\n", "\n")
    instruction = f"你将阅读一段来自{file_re_info}的病历文本，并根据病历内容回答一个问题。\n病历文本：\n{context_4_stem_vid}\n根据病历内容，请问{rule_info}"

    if not isinstance(gold_ans, str):
        print("*" * 100)
        print(instruction)
        print("*" * 100)
        print()
        return None
    
    gold_ans = gold_ans.strip("\"")
    target = ''
    if gold_ans == 'y':
        target = '是'
    elif gold_ans =='n':
        target = '否'
    else:
        phrases = []
        for choice in gold_ans.split('\\'):
            assert choice in ['a', 'b', 'c', 'd', 'UTD'], gold_ans
            phrase = convert_choice_to_phrase(choice, rule_info)
            assert phrase is not None
            phrases.append(phrase)
        target = '\n'.join(phrases)
    
    sample = {
        "instruction": instruction,
        "output": target,
        "history": None,
    }
    return sample

def get_precondition_2_secect_line(stem_cn_name,condition_info):
    """

    :param stem_cn_name:
    :param condition_info:
    :return:
    """
    if re.search("首",stem_cn_name):
        return condition_info.get("首次入院时间","")
    elif re.search("围术期",stem_cn_name):
        terms = condition_info.get("围术期",[])
        return terms
        # for term in terms:
        #     for start_time,end_time in term:
        #         start_time = int(start_time) -1
        #         end_time = int(end_time) +1
        #         return
    else:
        return ""
def is_filter_4_sec_index(precondition_re,sec_index):
    if isinstance(precondition_re, str):
        if re.search(precondition_re, sec_index):
            return False
    else:
        for pre_re in precondition_re:
            for start_time, end_time in pre_re:
                if start_time <= int(sec_index[-2]) <= end_time:
                    return False
    return True
def get_context_info_4_vid_4_stem(file_re_info,sec_index_re,cli_info_4_vid,line_re,stem_cn_name):
    # stem_cn_name: 如果是“首”相关，则医嘱规则增加 首次入院时间和sec_index中医嘱开始相同相同；
    #                 如果是“围术期”,则医嘱规则增加 医嘱开始和结束时间限制下 sec_index筛选条件
    context = ""
    # 获取前置条件
    precondition_re = get_precondition_2_secect_line(stem_cn_name,cli_info_4_vid.get("补充信息",{}))
    for file_name, cli_info in cli_info_4_vid.items():
        if re.search(file_re_info, file_name):
            for sec_index, sec_info in cli_info.items():
                if precondition_re:
                    if is_filter_4_sec_index(precondition_re, sec_index):
                       continue
                sec_index = re.sub("_\d{4,}","",sec_index)  # 删除掉时间信息
                if re.search(sec_index_re, sec_index):
                    # 通过line_re行筛选依据，过滤无用信息
                    if isinstance(sec_info,list):
                        line_str = "\n".join([x for x in sec_info if re.search(line_re,x)])
                    else:
                        line_str = sec_info if re.search(line_re,sec_info) else ""
                    context += line_str + '\n'
    return context
def get_all_stem_info():
    result_dict_path = os.path.join(prepro_orig_data_dir_path, "result_dict.json")
    with open(result_dict_path,"r",encoding="utf-8") as f:
        stem_info_dict = json.load(f)
    return stem_info_dict
def get_check_vids_info():
    # 读取就诊列表中的就诊id信息，并核对和解析的数据中vid是否相同
    with open(os.path.join(orig_data_dir_path,"3-就诊流水号列表.txt"),"r",encoding="utf-8") as f:
        all_vids = f.readlines()
    all_vids = [x.strip() for x in all_vids if x]
    prepro_vids = os.listdir(prepro_data_dir_path)
    assert len(all_vids) == len(prepro_vids)
    return all_vids
def get_cli_info_4_vid(vid_file_path,files_4_vid):
    # 读取该就诊下的所有病历信息
    cli_info_4_vid = {}
    for file_4_cli_info in files_4_vid:
        with open(os.path.join(vid_file_path, file_4_cli_info), "r", encoding="utf-8") as f:
            cli_info = json.load(f)
        cli_info_4_vid[file_4_cli_info[:-5]] = cli_info
    return cli_info_4_vid


def main():
    # 1. 读取stem的配置信息
    stem_info_dict = get_all_stem_info()
    # 2. 读取就诊流水号信息
    all_vids = get_check_vids_info()
    # 从标注文件获取每个就诊的各个数据项对应的答案
    gold_annotaion_path = "data/orig_datas/8-填报结果.xlsx"
    vid_2_stem_answer = get_gold_ans(gold_annotaion_path)
    sft_data_samples = []
    # 3. 生产每个就诊的每个stem问题结果
    for vid in all_vids:
        vid_file_path = os.path.join(prepro_data_dir_path,vid)
        files_4_vid = os.listdir(vid_file_path)
        # 3.1 加载该就诊下的所有转化格式后的病历信息
        cli_info_4_vid = get_cli_info_4_vid(vid_file_path,files_4_vid)
        # 3.2 依次获得每个stem的结果，需要根据有向无环图的顺序获取结果
        for stem_name,stem_info in stem_info_dict.items():
            stem_cn_name = stem_info["数据采集项"]
            stem_type = stem_info["数据类型"]
            stem_other_info = stem_info["备注"]
            stem_select_info = stem_info["选项列表"]
            stem_rule_info = stem_info["规则信息"]
            try:
                gold_ans = vid_2_stem_answer[vid][stem_name]
            except:
                print(f"标注文件中不包含就诊{vid}的数据项{stem_name}\n")
                continue
            
            # 3.3 通过stem信息获得结果
            for stem_info in stem_rule_info:
                if isinstance(stem_info,dict):
                    file_re_info = stem_info["文件名"].strip()
                    sec_index_re = stem_info["表索引"].strip()
                    line_re = stem_info["行筛选条件"].strip()
                    parser_fun = stem_info["解析方式"].strip()
                    rule_info = stem_info["规则"].strip()
                    # 3.4 获取该就诊关于该stem的相关病历内容。
                    context_4_stem_vid = get_context_info_4_vid_4_stem(file_re_info, sec_index_re, cli_info_4_vid,line_re,stem_cn_name)

                    if parser_fun != "模型":
                        continue
                    if not isinstance(gold_ans, str):
                        print(f"标注文件中就诊{vid}的数据项{stem_name}值为{gold_ans}，无效")
                    sample = get_sample_4_sft(file_re_info, rule_info, context_4_stem_vid, gold_ans)
                    if sample:
                        sft_data_samples.append(sample)
                else:
                    raise print(f"{vid}就诊中{stem_name}:{stem_cn_name}的stem_info应该解析为dict，但是实际为{stem_info}，错误！")
    
    save_sft_data_path = "sft_data.json"
    with open(save_sft_data_path, 'w') as f:
        json.dump(sft_data_samples, f, ensure_ascii=False, indent=4)

if __name__ == '__main__':
    main()

