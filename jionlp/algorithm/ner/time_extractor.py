# -*- coding=utf-8 -*-
# library: jionlp
# author: dongrixinyu
# license: Apache License 2.0
# email: dongrixinyu.89@163.com
# github: https://github.com/dongrixinyu/JioNLP
# description: Preprocessing & Parsing tool for Chinese NLP

"""
TODO:
    - ”据预测，到2025年，全球数据“ 无法将 到 识别出来
    - ”机怎么了：9年间四个子品“ 中，”9年间“ 无法被抽取，会抽取得到 ”9年“
    - “春天的时候”，其中，“的时候” 仅为时间修饰词，不具有任何含义，
        此时，时间无意义修饰词应当被包含在时间实体当中
        - “冬至那天”，其中的 “那天”、“这天” 等

"""


import re
import time
import cn2an
import jieba

from jionlp.rule.rule_pattern import TIME_CHAR_STRING, \
    FAKE_POSITIVE_START_STRING, FAKE_POSITIVE_END_STRING, REIGN_TITLE_CHAR_STRING
from jionlp.rule import extract_parentheses, remove_parentheses
from jionlp.gadget.time_parser import TimeParser
from enum import Enum
from jionlp.util.funcs import Q2B


class FilteredReason(Enum) :
    none = "none"
    fake_positive_start_pattern = "fake_positive_start_pattern"
    fake_positive_end_pattern = "fake_positive_end_pattern"
    strip_not_eq = "strip_not_eq"
    de_in_start_or_end = "的_in_start_or_end"
    paren_not_match = "paren_not_match"
    symbol_after_chinese = "symbol_after_chinese"
    cut_prev_word = "cut_prev_word"
    cut_post_word = "cut_post_word"


class TimeExtractor(object):
    """ 时间实体抽取器。不依赖模型，将文本中的时间实体进行抽取，并对其做时间语义解析。

    - TODO: ”2000“ 此类时间表达容易与某些金额、数量单位造成混淆，如”2000万美金“，”2000多台发动机“，因此需要
        首先考虑数量词表达，在2000非数量表达的情况下，再判定为 ”2000年“ 进行返回。
        目前就简，按四位数后是否有 ”万、亿、多万、多亿“ 进行判断，单位抽取与解析完成后再修复完整版。
    - 默认大概率非时间含义的时间表达默认不进行返回。
    - 若文本中包含 ”的“ 字，则在 parse_time 之前，先将此字消除后再进行解析。

    Args:
        text(str): 输入待抽取时间实体的文本
        time_base(int|datetime|dict|list): 若对文本中的时间实体进行语义解析，则须指定解析的时间基，默认为当前时间 time.time()
        with_parsing(bool): 指示返回结果是否包含解析信息，默认为 True
        ret_all(bool): 某些时间表达，在大多数情况下并非表达时间，如 ”一点“ 之于 ”他一点也不友善“，默认按绝大概率处理，
            即不返回此类伪时间表达，该参数默认为 False；若希望返回所有抽取到的时间表达，须将该参数置 True。
        其它(若干)属于 parse_time 的参数。参考 `jio.parse_time.__doc__`

    Returns:
        list(dict): 包含时间实体的列表，其中包括 text、type、offset 三个字段，和工具包中 NER 标准处理格式一致。

    Example：
        >>> import jionlp as jio
        >>> text = '8月临近尾声，中秋、国庆两个假期已在眼前。2021年中秋节是9月21日，星期二。'
                    有不少小伙伴翻看放假安排后，发现中秋节前要"补"假。
                    记者注意到，根据放假安排，9月18日（星期六）上班，9月19日至21日放假调休，也就是从周日开始放假3天。
                    由于中秋节后上班不到 10天，又将迎来一个黄金周—国庆长假，因此工作也就"安排"上了。
                    双节来袭，仍有人要坚守岗位。'
        >>> res = jio.ner.extract_time(text, time_base=time.time(), with_parsing=False)
        >>> print(res)
            {'text': '8月', 'offset': [41, 43], 'type': 'time_point'}
            {'text': '中秋', 'offset': [48, 50], 'type': 'time_point'}
            {'text': '国庆', 'offset': [51, 53], 'type': 'time_point'}
            {'text': '2021年中秋节', 'offset': [62, 70], 'type': 'time_point'}
            {'text': '9月21日', 'offset': [71, 76], 'type': 'time_point'}
            {'text': '星期二', 'offset': [77, 80], 'type': 'time_point'}
            {'text': '中秋节前', 'offset': [98, 102], 'type': 'time_span'}
            {'text': '9月18日', 'offset': [136, 141], 'type': 'time_point'}
            {'text': '星期六', 'offset': [142, 145], 'type': 'time_point'}
            {'text': '9月19日至21日', 'offset': [149, 158], 'type': 'time_span'}

    """
    def __init__(self):
        self.parse_time = None
        self.forbidden_range = []

    def _prepare(self):
        self.parse_time = TimeParser()
        recall_string_re = "(" + REIGN_TITLE_CHAR_STRING + TIME_CHAR_STRING[1:]
        #print(recall_string_re)
        self.time_string_pattern = re.compile(recall_string_re)  # 该正则存在假阴风险

        self.fake_positive_start_pattern = re.compile(FAKE_POSITIVE_START_STRING)
        self.fake_positive_end_pattern = re.compile(FAKE_POSITIVE_END_STRING)

        # 此类表达虽然可按时间解析，但是文本中很大概率并非表示时间，故以大概率进行排除，
        # 并设参数 ret_all，即返回所有进行控制，默认为 False，即根据词典进行删除
        self.non_time_string_list = [
            '一点', '0时', '一日', '黎明', '十分', '百分', '万分']
        # 一点也不大方、一日之计在于晨、黎明主演电影、

        self.num_pattern = re.compile(r'[０-９0-9]')
        self.four_num_year_pattern = re.compile(r'^[\d]{4}$')
        self.unit_pattern = re.compile(r'(多)?[万亿元]')  # 四数字后接单位，说明非年份

        self.single_char_time = set(['春', '夏', '秋', '冬'])
        self.filtered_reason = FilteredReason.none
    
    def digit_chinese_mixed(self, sub_string):
        p1 = re.compile(r"\d+")
        p2 = re.compile(r"[一二三四五六七八九十百千万零〇]+")
        if re.search(p1, sub_string) and re.search(p2, sub_string):
            return True
        else:
            return False

    def __call__(self, text, time_base=time.time(), with_parsing=True, ret_all=False,
                 ret_type='str', ret_future=False, period_results_num=None):
        if self.parse_time is None:
            self._prepare()

        text = "".join([Q2B(u) for u in text])
        self.widx = []
        for i, w in enumerate(jieba.cut(text)):
            self.widx.extend([i for _ in range(len(w))])
        #print(self.widx)
        #print(jieba.lcut(text))
        self.percent_match(text)
        candidates_list = self.extract_time_candidates(text)

        time_entity_list = list()
        for candidate in candidates_list:
            offset = [0, 0]
            bias = 0
            #print(" handle candidate: ", candidate)
            while candidate['offset'][0] + offset[1] < candidate['offset'][1]:
                # 此循环意在找出同一个 candidate 中包含的多个 time_entity

                true_string, result, offset = self.grid_search(
                    candidate['time_candidate'][bias:], time_base=time_base,
                    ret_type=ret_type, ret_future=ret_future,
                    period_results_num=period_results_num,
                    base_offset=candidate['offset'][0]+bias)

                if true_string is not None:

                    # rule 1: 判断字符串是否为大概率非时间语义
                    if (true_string in self.non_time_string_list) and (not ret_all):
                        bias += offset[1]
                        continue

                    # rule 2: 判断四数字 ”2033“ 是否后接货币、非年份量词
                    if self.four_num_year_pattern.search(true_string):
                        back_start = candidate['offset'][0] + bias + offset[1]
                        if self.unit_pattern.search(text[back_start: back_start + 2]):
                            # 说明非真实年份，跳回
                            bias += offset[1]
                            continue
                    dig_chn_mixed = self.digit_chinese_mixed(true_string)
                    has_wrong_info = result["something_wrong"] or dig_chn_mixed if "something_wrong" in result else dig_chn_mixed
                    if with_parsing:
                        time_entity_list.append(
                            {'text': true_string,
                             'offset': [candidate['offset'][0] + bias + offset[0],
                                        candidate['offset'][0] + bias + offset[1]],
                             'type': result['type'],
                             'something_wrong': has_wrong_info,
                             'detail': result})
                    else:
                        time_entity_list.append(
                            {'text': true_string,
                             'offset': [candidate['offset'][0] + bias + offset[0],
                                        candidate['offset'][0] + bias + offset[1]],
                             'something_wrong': has_wrong_info,
                             'detail': result,
                             'type': result['type']})
                    bias += offset[1]
                else:
                    break

        # for item in time_entity_list:
        #     assert item['text'] == text[item['offset'][0]: item['offset'][1]]
        #     print(item)
        return time_entity_list

    def _filter(self, sub_string, offset, base_offset):
        """ 对某些易造成实体错误的字符进行过滤。
        此问题产生的原因在于，parse_time 工具对某些不符合要求的字符串也能成功解析，造成假阳性。
        """
        if self.fake_positive_start_pattern.search(sub_string[0]):
            self.filtered_reason = FilteredReason.fake_positive_start_pattern
            return False

        if self.fake_positive_end_pattern.search(sub_string[-1]):
            self.filtered_reason = FilteredReason.fake_positive_end_pattern
            return False

        if len(sub_string) != len(sub_string.strip()):
            self.filtered_reason = FilteredReason.strip_not_eq
            return False

        # 的 不可以在句首或句尾
        if '的' in sub_string[0] or '的' in sub_string[-1]:
            self.filtered_reason = FilteredReason.de_in_start_or_end
            return False

        # 括号造成的边界错误
        if sub_string[0] in ')）' or sub_string[-1] in '(（':
            self.filtered_reason = FilteredReason.paren_not_match
            return False
        # 汉字后面有点号
        if sub_string.endswith(".") and not re.match(r"[a-zA-Z0-9]", sub_string[-2]):
            self.filtered_reason = FilteredReason.symbol_after_chinese
            return False

        # 时间片段不能切割词语，比如"希腊月GDP"中"腊月"切割了"希腊"
        rawoffset = [x+base_offset for x in offset]
        #print("IN filter:",sub_string, rawoffset)
        if rawoffset[0] > 0 and self.widx[rawoffset[0]] == self.widx[rawoffset[0]-1]:
            #print(matched_res.group(), " 0cut word: ", "".join([text[jj] for jj in range(len(text)) if widx[jj] == widx[start_idx]]))
            self.filtered_reason = FilteredReason.cut_prev_word
            return False
        if rawoffset[1] < len(self.widx) and self.widx[rawoffset[1]-1] == self.widx[rawoffset[1]]:
            #print(matched_res.group(), " 1cut word: ", "".join([text[jj] for jj in range(len(text)) if widx[jj] == widx[end_idx-1]]))
            self.filtered_reason = FilteredReason.cut_post_word
            return False

        self.filtered_reason = FilteredReason.none
        return True

    def _grid_search_1(self, time_candidate):
        """ 取消 parse_time 中 strict 限制，从长至短，先左后右依次缩短 time_candidate，
        直到解析错误或解析结果出错
        """
    def year_after_format(self, sub_string):
        pattern = re.compile(r"\d{1,2}/\d{1,2}/\d{4}")
        a = sub_string
        for m in re.finditer(pattern, a):
            start, end = m.span()
            a = a[:start]+a[end-4:end] +"/" +a[start:end-5]+a[end:]
        return a

    def replace_parse(self, sub_string_for_parse, time_base, strict,
                    ret_type, ret_future, period_results_num):
        p = re.compile(r"([0-9]+|[一二三四五六七八九十〇零]+)")
        for m in re.finditer(p, sub_string_for_parse):
            start, end = m.span()
            number = 0
            try:
                number = int(sub_string_for_parse[start:end])
            except:
                try:
                    number = cn2an.cn2an(sub_string_for_parse[start:end])
                except:
                    continue
            if end < len(sub_string_for_parse) and sub_string_for_parse[end] == '年':
                if number > 50000:
                    continue
            elif number > 300:
                continue
            replaced_sub_string = sub_string_for_parse[:start] + "12" + sub_string_for_parse[end:]
            #print(" -> replaced:", replaced_sub_string)
            try:
                result = self.parse_time(
                    replaced_sub_string, time_base=time_base, strict=True,
                    ret_type=ret_type, ret_future=ret_future,
                    period_results_num=period_results_num)
                return result, replaced_sub_string
            except:
                continue
        try:
            na = sub_string_for_parse
            for _ in range(100):
                m = re.search(re.compile(r"\d+"), na)
                if m:
                    na = na[:m.span()[0]] + cn2an.an2cn(m.group(0)) + na[m.span()[1]:]
                else:
                    break
            #print(" -> replaced:", na)
            result = self.parse_time(
                    na, time_base=time_base, strict=True,
                    ret_type=ret_type, ret_future=ret_future,
                    period_results_num=period_results_num)
            return result, na
        except:
            pass
        try:
            na = sub_string_for_parse
            for _ in range(100):
                m = re.search(re.compile(r"[一二三四五六七八九十百千万〇零]+"), na)
                if m:
                    na = na[:m.span()[0]] + str(cn2an.cn2an(m.group(0))) + na[m.span()[1]:]
                else:
                    break
            #print(" -> replaced:", na)
            result = self.parse_time(
                    na, time_base=time_base, strict=True,
                    ret_type=ret_type, ret_future=ret_future,
                    period_results_num=period_results_num)
            return result, na
        except (ValueError, Exception):
            pass
        return None, None
    
    def grid_search(self, time_candidate, time_base=time.time(),
                    ret_type='str', ret_future=False, period_results_num=None,
                    base_offset=0):
        """ 全面搜索候选时间字符串，从长至短，较优 """
        length = len(time_candidate)
        for i in range(length):  # 控制总长，若想控制单字符的串也被返回考察，此时改为 length + 1
            for j in range(i):  # 控制偏移
                offset = [j, length - i + j + 1]
                sub_string = time_candidate[j: offset[1]]
                #print(" --> grid_search:", sub_string)
                # 处理假阳性。检查子串，对某些产生歧义的内容进行过滤。
                # 原因在于，parse_time 会对某些不符合要求的字符串做正确解析.
                if not self._filter(sub_string, offset, base_offset):
                    #print("filted:[{}]".format(sub_string), self.filtered_reason)
                    continue

                # rule 3: 若子串中包含 ”的“ 字会对结果产生影响，则先将 ”的“ 字删除后再进行解析。
                sub_string_for_parse = sub_string.replace('的', '')

                # 形如10/01/2000 10:00:41.01这样的格式，无法识别，需要交换年的位置
                sub_string_for_parse = self.year_after_format(sub_string_for_parse)
                
                # rule 4: 字符串中若包含空格，会对结果产生影响，则先将 “ ” 删除后解析。
                sub_string_for_parse = sub_string_for_parse.replace(' ', '')

                # rule 5: 对于一些特殊的补充性时间字符串，也需要特殊对待，将括号去除后再进行解析。
                # 一般为 周 对 日的补充，如“2021年11月1日（下周一晚）19:30-20:30”
                # 该规则依然简陋，稳定性不够好
                sub_parentheses = extract_parentheses(sub_string_for_parse, parentheses='()（）')
                if '周' in ''.join(sub_parentheses) or '星期' in ''.join(sub_parentheses):
                    sub_string_for_parse = remove_parentheses(sub_string_for_parse, parentheses='()（）')
                    if len(sub_string_for_parse) < 1:
                        continue
                # rule 6: 对于数字为起始或结尾的字符串，过滤之。
                # 如：342127197212178212 将 2017 和 1972 抽取为年份
                if self.num_pattern.search(sub_string_for_parse[0]):
                    if j - 1 >= 0:
                        if self.num_pattern.search(time_candidate[j - 1]):
                            continue
                if self.num_pattern.search(sub_string_for_parse[-1]):
                    if offset[1] < length:
                        if self.num_pattern.search(time_candidate[offset[1]]):
                            continue
                #print("sub_string_for_parse with parse_time:[{}]".format(sub_string_for_parse))
                try:
                    result = self.parse_time(
                        sub_string_for_parse, time_base=time_base, strict=True,
                        ret_type=ret_type, ret_future=ret_future,
                        period_results_num=period_results_num)

                    return sub_string, result, offset
                except Exception:
                    #print(e, "try again after replace")
                    # 如果替换掉部分数字，结果可解析，也认为是正确的
                    replaced_result, replaced_str = self.replace_parse(sub_string_for_parse, 
                        time_base=time_base, strict=True,
                        ret_type=ret_type, ret_future=ret_future,
                        period_results_num=period_results_num)
                    #print(replaced_result, replaced_str)
                    if replaced_result is None:
                        continue
                    else:
                        replaced_result["something_wrong"] = True
                        replaced_result["replaced"] = replaced_str
                        return sub_string, replaced_result, offset

        return None, None, None


    def _grid_search_2(self, time_candidate):
        """ 全面搜索候选时间字符串，从前至后，从长至短 """
        #print(time_candidate)
        length = len(time_candidate)
        for i in range(length - 1):  # 控制起始点
            for j in range(length, i, -1):  # 控制终止点
                try:
                    offset = [i, j]
                    sub_string = time_candidate[i: j]
                    #print(sub_string)
                    # 处理假阳性。检查子串，对某些产生歧义的内容进行过滤。
                    # 原因在于，parse_time 会对某些不符合要求的字符串做正确解析.
                    if not TimeExtractor._filter(sub_string):
                        continue

                    result = self.parse_time(sub_string, strict=True)

                    return sub_string, result, offset
                except (ValueError, Exception):
                    continue

        return None, None, None

    def percent_match(self, text):
        p = re.compile(r"(百分之[零一二三四五六七八九十〇点]+|[点零一二三四五六七八九十〇]+个百分点)")
        for m in re.finditer(p, text):
            #print(m.group(), m.span())
            self.forbidden_range.append(m.span())
    def overlap_forbidden_range(self, start_idx, end_idx):
        for r in self.forbidden_range:
            if not(start_idx >= r[1] or end_idx <= r[0]):
                return True
        return False

    def extract_time_candidates(self, text):
        """ 获取所有的候选时间字符串，其中包含了时间实体 """
        text_length = len(text)
        idx_count = 0
        time_candidates_list = list()
        while idx_count < text_length:
            matched_res = self.time_string_pattern.search(text[idx_count:])
            # print(matched_res)
            if matched_res is not None:
                start_idx = idx_count + matched_res.span()[0]
                end_idx = idx_count + matched_res.span()[1]
                if self.overlap_forbidden_range(start_idx, end_idx):
                    idx_count += matched_res.span()[1]
                    #print(" --> overlap:", matched_res.group(), start_idx, end_idx)
                    continue
                if len(matched_res.group()) > 1:
                    time_candidates_list.append(
                        {'time_candidate': matched_res.group(),
                         'offset': [start_idx, end_idx]})
                elif matched_res.group() in self.single_char_time:
                    # 可能误打 “春”、“夏” 等单字符时间表达，故在此加入
                    time_candidates_list.append(
                        {'time_candidate': matched_res.group(),
                         'offset': [start_idx, end_idx]})
                idx_count += matched_res.span()[1]
            else:
                break
        #for tc in time_candidates_list:
        #    print("{} 候选：{}".format(" -> ", tc))
        return time_candidates_list


if __name__ == '__main__':
    text = '''【标题：中秋国庆双节都加班，可拿24天的日工资】
        8月临近尾声，中秋、国庆两个假期已在眼前。2021年中秋节是9月21日，星期二。 有不少小伙伴翻看放假安排后，发现中秋节前后两个周末都要"补"假。
        记者注意到，根据放假安排，9月18日（星期六）上班，9月19日至21日放假调休，也就是从周日开始放假3天。由于中秋节后上班不到 10天，又将迎来一个黄金周—国庆长假，因此工作也就"安排"上了。
        双节来袭，仍有人要坚守岗位。加班费怎么算？记者为辛勤的小伙伴们算了一笔账。今年中秋加上国庆，两个假日加在一起共有10个加班日，如果全部加班，则可以拿到相当于24天的日工资。
        根据规定，9月21日中秋节和10月1日、2日、3日均为法定假日，用人单位安排劳动者加班工作，应按照不低于劳动者本人日或小时工资的300%支付加班工资；
        9月19日、20日和10月4日、5日、6日、7 日，用人单位可选择给予补休或按照不低于劳动者本人日或小时工资的200%支付加班工资。也就是说，如果10天全部加班，就可以拿到24天的日工资收入。
        人社部门提醒，当然这只是按照最低工资标准算的最低加班费，实际情况中，加班工资应该与个人实际工资挂钩。'''

    extract_time = TimeExtractor()
    res = extract_time(text, with_parsing=False)
    print(res)

