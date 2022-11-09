# -*- coding=utf-8 -*-
# library: jionlp
# author: dongrixinyu
# license: Apache License 2.0
# Email: dongrixinyu.89@163.com
# github: https://github.com/dongrixinyu/JioNLP
# description: Preprocessing tool for Chinese NLP


def bracket(regular_expression):
    return ''.join([r'(', regular_expression, r')'])


def bracket_absence(regular_expression):
    return ''.join([r'(', regular_expression, r')?'])


def absence(regular_expression):
    return ''.join([regular_expression, r'?'])


def start_end(regular_expression):
    return ''.join([r'^', regular_expression, r'$'])

def Q2B(uchar):
    """单个字符 全角转半角""" 
    inside_code = ord(uchar) 
    if inside_code == 0x3000: 
        inside_code = 0x0020 
    else: 
        inside_code -= 0xfee0 
    if inside_code < 0x0020 or inside_code > 0x7e: 
        #转完之后不是半角字符返回原来的字符 
        return uchar 
    return chr(inside_code)


