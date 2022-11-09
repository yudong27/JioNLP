import time
import json
import jionlp as jio
import sys
import jieba
import re

text = '''
20000年巴拿马总统莫斯科索在15号召开记者会，武装分子杀害一名12岁儿童并打伤12人，伤者中有3名警察。2000年十二月
马上要到来得十五月份，淳熙8年.周1开会。一百二十岁.到了99年(应为到了1999年)，淳熙8年(淳熙八年)，
二0年(20年).今年腊月12台手机被寄出。今年腊月12台湾又出新闹剧。今年腊月1200台手机。今年希腊月GPD不如去年。
在吉隆坡结束为期3天的飞弹会谈.比一九九三年提高了四点一个百分点。
'''
print(text)
res = jio.ner.extract_time(text, time_base=time.time(), with_parsing=False)
for t in res:
    print(t)